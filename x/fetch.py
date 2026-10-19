#!/usr/bin/env python3
"""X scan, step 1 of 2: pull the posts taking off on X. From the repo root:

    python3 x/fetch.py

Runs one X API v2 recent search per topic query (official API, bearer token,
see x_api.py), keeps posts with --min-likes or more, and writes them to
x/.posts.json (not committed) for the refresh session to group into stories
(x/CLUSTERING.md). Step 2 is x/finish.py.

On failure it logs an x_scan error to data/refresh_log.json, leaves
data/x_trends.json as it was, and exits 1.
"""

import argparse
import html
import os
import sys
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import POSTS_PATH, iso, load_json, log_x_scan, now_utc, parse_time, write_json  # noqa: E402
from x_api import XClient, XError  # noqa: E402

# One search per topic. The X API has no likes filter, so --min-likes is applied here.
QUERIES = [
    '(claude OR anthropic OR "claude code" OR opus OR sonnet)',
    '(openai OR chatgpt OR codex OR "gpt-5" OR sora OR "sam altman")',
    '(gemini OR deepmind OR "google ai" OR veo OR grok OR xai)',
    '(deepseek OR qwen OR mistral OR llama OR "open source model" OR "hugging face" OR kimi OR glm)',
    '("ai agent" OR "ai agents" OR llm OR "vibe coding" OR cursor OR perplexity OR "new model" OR agi)',
]
FILTERS = "lang:en -is:reply -is:retweet"
STOP_CODES = (" HTTP 401", " HTTP 402", " HTTP 403", " HTTP 429")  # bad token, plan or rate limit: stop


def normalize(tweet, users, now):
    m = tweet.get("public_metrics", {})
    user = users.get(tweet.get("author_id"), {})
    username = user.get("username") or "i"
    posted = parse_time(tweet["created_at"])
    age_h = max((now - posted).total_seconds() / 3600, 1.0)
    text = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text", "")
    return {
        "id": tweet["id"],
        "url": f"https://x.com/{username}/status/{tweet['id']}",
        "author": "@" + username,
        "author_followers": user.get("public_metrics", {}).get("followers_count"),
        "text": html.unescape(text),
        "likes": m.get("like_count", 0),
        "reposts": m.get("retweet_count", 0),
        "quotes": m.get("quote_count", 0),
        "replies": m.get("reply_count", 0),
        "views": m.get("impression_count"),
        "posted_at": iso(posted),
        "velocity_per_hour": round(m.get("like_count", 0) / age_h, 1),
    }


def run(client, queries, now, window_hours=24, max_results=100, min_likes=200):
    """Returns (posts sorted by likes, searches that worked, error messages)."""
    start = iso(now - timedelta(hours=window_hours))
    posts, ok, errors = {}, 0, []
    for i, q in enumerate(queries):
        try:
            tweets, users = client.search_recent(q, start, max_results)
        except Exception as e:
            errors.append(f"search {i + 1}: {e}")
            if isinstance(e, XError) and any(c in str(e) for c in STOP_CODES):
                break
            continue
        ok += 1
        for t in tweets:
            p = normalize(t, users, now)
            if p["likes"] < min_likes:
                continue
            if p["id"] in posts:
                posts[p["id"]]["queries"].append(i + 1)
            else:
                posts[p["id"]] = {**p, "queries": [i + 1]}
    return sorted(posts.values(), key=lambda p: -p["likes"]), ok, errors


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="data", help="data directory (default: data)")
    p.add_argument("--window-hours", type=int, default=24, help="how far back to search (max 168)")
    p.add_argument("--max-results", type=int, default=100,
                   help="posts read per search, 10-100 (each one counts against the X API plan)")
    p.add_argument("--min-likes", type=int, default=200, help="drop posts below this many likes")
    args = p.parse_args(argv)

    t0, now = time.monotonic(), now_utc()
    client = XClient()
    queries = [f"{q} {FILTERS}" for q in QUERIES]
    posts, ok, errors = run(client, queries, now, args.window_hours, args.max_results, args.min_likes)

    if not posts:
        msg = errors[0] if errors else f"no posts with {args.min_likes}+ likes in the last {args.window_hours}h"
        log_x_scan(args.data, "error", msg, time.monotonic() - t0, {"posts_read": client.posts_read})
        if os.path.exists(POSTS_PATH):
            os.remove(POSTS_PATH)
        print(f"x_scan FAILED: {msg}", file=sys.stderr)
        return 1

    prev = load_json(os.path.join(args.data, "x_trends.json"), {})
    previous_stories = [] if prev.get("sample") else [
        {"id": s["id"], "title": s.get("title"), "keywords": s.get("keywords", [])}
        for s in prev.get("stories", [])]
    write_json(POSTS_PATH, {
        "fetched_at": iso(now),
        "duration_s": round(time.monotonic() - t0),
        "window_hours": args.window_hours,
        "min_likes": args.min_likes,
        "queries": queries,
        "searches_ok": ok,
        "errors": errors,
        "posts_read": client.posts_read,
        "previous_stories": previous_stories,
        "posts": posts,
    })
    print(f"x_scan ok: {len(posts)} posts with {args.min_likes}+ likes from {ok}/{len(queries)} searches "
          f"({client.posts_read} read)" + (f"; {len(errors)} failed: {errors[0]}" if errors else ""))
    print("Next: group them into stories in x/.stories.json (x/CLUSTERING.md), then run python3 x/finish.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
