#!/usr/bin/env python3
"""X scan, step 2 of 2: turn the session's story grouping into data/x_trends.json.

    python3 x/finish.py                  # after writing x/.stories.json (x/CLUSTERING.md)
    python3 x/finish.py --error "<why>"  # log a failed scan, keep the old file

Checks x/.stories.json against x/.posts.json, computes each story's metrics
and heat from its posts, writes data/x_trends.json (hottest first, at most 15)
and logs the run. If it lists problems, fix x/.stories.json and run it again.
"""

import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import POSTS_PATH, STORIES_PATH, load_json, log_x_scan, write_json  # noqa: E402

MAX_STORIES = 15
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VELOCITY_FOR_100 = 5000
HEAT_FORMULA = ("velocity = sum of likes per hour (likes / post age) over the story's posts; "
                f"heat = 100 * log10(1+velocity)/log10(1+{VELOCITY_FOR_100}), "
                "+5% per extra author up to +20%")
SAMPLE_NOTE = ("metrics cover the top posts xAI's X Search returns for these queries (min {min_likes} likes), "
               "not every post on X; a count X Search didn't show is taken as the minimum")


def check(doc, posts):
    """Problems with the session's story file, as a list of strings."""
    if not isinstance(doc, dict) or not isinstance(doc.get("stories"), list):
        return ['x/.stories.json must be {"stories": [...]}']
    stories = doc["stories"]
    problems = []
    if not stories:
        problems.append("no stories")
    if len(stories) > MAX_STORIES:
        problems.append(f"{len(stories)} stories, max {MAX_STORIES}: keep the hottest")
    ids, used = set(), {}
    for i, s in enumerate(stories):
        at = f"stories[{i}]"
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not SLUG.match(sid):
            problems.append(f"{at}.id must be a kebab-case slug")
            continue
        at = f"{at} ({sid})"
        if sid in ids:
            problems.append(f"{at}: duplicate id")
        ids.add(sid)
        title = s.get("title")
        if not isinstance(title, str) or not 0 < len(title.strip()) <= 100:
            problems.append(f"{at}.title must be 1-100 characters")
        summary = s.get("summary")
        if not isinstance(summary, str) or not 0 < len(summary.strip()) <= 400:
            problems.append(f"{at}.summary must be 1-400 characters")
        kw = s.get("keywords")
        if not isinstance(kw, list) or not 2 <= len(kw) <= 6 or not all(isinstance(k, str) and k.strip() for k in kw):
            problems.append(f"{at}.keywords must be 2-6 non-empty strings")
        pids = s.get("post_ids")
        if not isinstance(pids, list) or not pids:
            problems.append(f"{at}.post_ids must list at least one post id")
            continue
        for pid in pids:
            pid = str(pid)
            if pid not in posts:
                problems.append(f"{at}: post {pid} is not in x/.posts.json")
            elif pid in used and used[pid] != sid:
                problems.append(f"{at}: post {pid} is already in {used[pid]}")
            used.setdefault(pid, sid)
    return problems


def heat(velocity, authors):
    base = 100 * math.log10(1 + velocity) / math.log10(1 + VELOCITY_FOR_100)
    return max(0, min(100, round(base * (1 + min(0.2, 0.05 * (authors - 1))))))


def trim(text, n=280):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def build(stories, posts):
    out = []
    for s in stories:
        ps = sorted({str(i): posts[str(i)] for i in s["post_ids"]}.values(), key=lambda p: -p["likes"])
        velocity = sum(p["velocity_per_hour"] for p in ps)
        views = [p["views"] for p in ps if p.get("views") is not None]
        metrics = {"posts": len(ps), "likes": sum(p["likes"] for p in ps),
                   "reposts": sum(p["reposts"] for p in ps), "velocity_per_hour": round(velocity)}
        if views:
            metrics["views"] = sum(views)
        out.append({
            "id": s["id"],
            "title": s["title"].strip(),
            "summary": s["summary"].strip(),
            "keywords": [k.strip().lower() for k in s["keywords"]],
            "first_seen": min(p["posted_at"] for p in ps),
            "heat": heat(velocity, len({p["author"] for p in ps})),
            "metrics": metrics,
            "top_posts": [{"url": p["url"], "author": p["author"], "text": trim(p["text"]),
                           "likes": p["likes"], "reposts": p["reposts"], "views": p.get("views"),
                           "posted_at": p["posted_at"]} for p in ps[:3]],
        })
    return sorted(out, key=lambda s: -s["heat"])[:MAX_STORIES]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="data", help="data directory (default: data)")
    p.add_argument("--error", help="log a failed scan with this reason and keep the old file")
    args = p.parse_args(argv)

    if args.error:
        log_x_scan(args.data, "error", args.error)
        print(f"x_scan error logged: {args.error}")
        return 0

    fetched = load_json(POSTS_PATH, None)
    if fetched is None:
        print("x/.posts.json missing: run python3 x/fetch.py first", file=sys.stderr)
        return 1
    posts = {p["id"]: p for p in fetched["posts"]}
    doc = load_json(STORIES_PATH, None)
    problems = ["x/.stories.json missing"] if doc is None else check(doc, posts)
    if problems:
        print("x/.stories.json has problems; fix them and run this again:", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1

    stories = build(doc["stories"], posts)
    write_json(os.path.join(args.data, "x_trends.json"), {
        "schema_version": 1,
        "generated_at": fetched["fetched_at"],
        "sample": False,
        "window_hours": fetched["window_hours"],
        "queries": fetched["queries"],
        "heat_formula": HEAT_FORMULA,
        "sample_note": SAMPLE_NOTE.format(min_likes=fetched["min_likes"]),
        "stories": stories,
    })
    errors = fetched.get("errors", [])
    msg = f"{len(stories)} stories from {len(posts)} posts across {fetched['searches_ok']} searches"
    if fetched.get("cost_usd"):
        msg += f" (xAI ${fetched['cost_usd']:.2f})"
    if errors:
        msg += f"; {len(errors)} failed: {errors[0]}"
    log_x_scan(args.data, "partial" if errors else "ok", msg, fetched.get("duration_s", 0),
               {"stories": len(stories), "posts": len(posts), "posts_fetched": fetched.get("posts_fetched", 0),
                "cost_usd": fetched.get("cost_usd", 0)})
    print(f"x_scan {'partial' if errors else 'ok'}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
