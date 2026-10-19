#!/usr/bin/env python3
"""X scan, step 1 of 2: pull the posts taking off on X. From the repo root:

    python3 x/fetch.py

Runs one Grok request with xAI's X Search tool per topic query (see
xai_api.py), keeps the posts Grok cites from the search results, and writes
them to x/.posts.json (not committed) for the refresh session to group into
stories (x/CLUSTERING.md). Step 2 is x/finish.py.

On failure it logs an x_scan error to data/refresh_log.json, leaves
data/x_trends.json as it was, and exits 1.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import POSTS_PATH, iso, load_json, log_x_scan, now_utc, write_json  # noqa: E402
from xai_api import XAIClient, XAIError  # noqa: E402

# One search per topic, in X's own search syntax, which X Search understands.
QUERIES = [
    '(claude OR anthropic OR "claude code" OR opus OR sonnet)',
    '(openai OR chatgpt OR codex OR "gpt-5" OR sora OR "sam altman")',
    '(gemini OR deepmind OR "google ai" OR veo OR grok OR xai)',
    '(deepseek OR qwen OR mistral OR llama OR "open source model" OR "hugging face" OR kimi OR glm)',
    '("ai agent" OR "ai agents" OR llm OR "vibe coding" OR cursor OR perplexity OR "new model" OR agi)',
]
FILTERS = "min_faves:{min_likes} -is:retweet -is:reply lang:en"
STOP_CODES = (" HTTP 401", " HTTP 402", " HTTP 403", " HTTP 429")  # bad key, credits or rate limit: stop
STATUS_URL = re.compile(r"(?:x|twitter)\.com/(\w+)/status/(\d+)")
X_EPOCH_MS = 1288834974657  # post ids are snowflakes: (id >> 22) + this = posted time in ms

COUNT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The post's URL, exactly as the search returned it"},
            "username": {"type": "string", "description": "The author's X handle, without the @"},
            "text": {"type": "string", "description": "The full text of the post"},
            "likes": {**COUNT, "description": "Like count shown in the search results, or null"},
            "reposts": {**COUNT, "description": "Repost count shown in the search results, or null"},
            "views": {**COUNT, "description": "View count shown in the search results, or null"},
        },
        "required": ["url", "username", "text", "likes", "reposts", "views"],
        "additionalProperties": False,
    }}},
    "required": ["posts"],
    "additionalProperties": False,
}
PROMPT = """Search X with this exact query: {query}

Return up to {limit} of the posts it finds, the most liked first, exactly as the search returned them: the post URL, \
the author's handle, the full text, and the like, repost and view counts the results show (null for a count they \
don't show). Only include posts the search returned. Don't make up, merge or paraphrase posts."""


def posted_time(post_id):
    return datetime.fromtimestamp(((int(post_id) >> 22) + X_EPOCH_MS) / 1000, tz=timezone.utc)


def normalize(raw, cited_ids, now, min_likes):
    """A post from Grok's answer, or None if the search didn't return it."""
    m = STATUS_URL.search(raw.get("url") or "")
    if not m or m.group(2) not in cited_ids:
        return None
    pid = m.group(2)
    handle = m.group(1) if m.group(1) != "i" else (raw.get("username") or "i").lstrip("@")
    posted = posted_time(pid)
    likes = raw.get("likes")
    # The query's min_faves guarantees min_likes, so that is the floor when Grok gives no count.
    likes = likes if isinstance(likes, int) and likes >= min_likes else min_likes
    age_h = max((now - posted).total_seconds() / 3600, 1.0)
    return {
        "id": pid,
        "url": f"https://x.com/{handle}/status/{pid}",
        "author": "@" + handle,
        "text": (raw.get("text") or "").strip(),
        "likes": likes,
        "reposts": raw["reposts"] if isinstance(raw.get("reposts"), int) else 0,
        "views": raw["views"] if isinstance(raw.get("views"), int) else None,
        "posted_at": iso(posted),
        "velocity_per_hour": round(likes / age_h, 1),
    }


def run(client, queries, now, window_hours=24, per_query=25, min_likes=200, max_turns=4):
    """Returns (posts sorted by likes, searches that worked, error messages, uncited posts dropped)."""
    since = now - timedelta(hours=window_hours)
    posts, ok, errors, dropped = {}, 0, [], 0
    for i, q in enumerate(queries):
        try:
            answer, cited = client.x_search(PROMPT.format(query=q, limit=per_query), SCHEMA,
                                            since.date().isoformat(), max_turns)
        except Exception as e:
            errors.append(f"search {i + 1}: {e}")
            if isinstance(e, XAIError) and any(c in str(e) for c in STOP_CODES):
                break
            continue
        ok += 1
        cited_ids = {m.group(2) for m in map(STATUS_URL.search, cited) if m}
        for raw in answer.get("posts") or []:
            p = normalize(raw, cited_ids, now, min_likes)
            if p is None:
                dropped += 1
            elif p["posted_at"] < iso(since):
                continue
            elif p["id"] in posts:
                posts[p["id"]]["queries"].append(i + 1)
            else:
                posts[p["id"]] = {**p, "queries": [i + 1]}
    return sorted(posts.values(), key=lambda p: -p["likes"]), ok, errors, dropped


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="data", help="data directory (default: data)")
    p.add_argument("--window-hours", type=int, default=24, help="how far back posts count")
    p.add_argument("--per-query", type=int, default=25, help="posts to ask Grok for per search")
    p.add_argument("--min-likes", type=int, default=200, help="X's min_faves: in every query")
    p.add_argument("--model", default="grok-4.7", help="xAI model that runs the searches")
    p.add_argument("--max-turns", type=int, default=4, help="bounds the searches (and cost) per request")
    args = p.parse_args(argv)

    t0, now = time.monotonic(), now_utc()
    client = XAIClient(model=args.model)
    queries = [f"{q} {FILTERS.format(min_likes=args.min_likes)}" for q in QUERIES]
    posts, ok, errors, dropped = run(client, queries, now, args.window_hours, args.per_query,
                                     args.min_likes, args.max_turns)
    usage = {"posts_fetched": client.posts_fetched, "cost_usd": round(client.cost_usd, 4)}

    if not posts:
        msg = errors[0] if errors else f"no posts with {args.min_likes}+ likes in the last {args.window_hours}h"
        if dropped and not errors:
            msg += f" ({dropped} posts in Grok's answers were not in its search results)"
        log_x_scan(args.data, "error", msg, time.monotonic() - t0, usage)
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
        "dropped_uncited": dropped,
        **usage,
        "previous_stories": previous_stories,
        "posts": posts,
    })
    print(f"x_scan ok: {len(posts)} posts with {args.min_likes}+ likes from {ok}/{len(queries)} searches "
          f"(xAI cost ${usage['cost_usd']:.2f})" + (f"; {len(errors)} failed: {errors[0]}" if errors else ""))
    print("Next: group them into stories in x/.stories.json (x/CLUSTERING.md), then run python3 x/finish.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
