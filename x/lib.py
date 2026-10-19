"""Shared helpers for the X scan steps (fetch.py, finish.py)."""

import json
import os
from datetime import datetime, timezone

LOG_MAX = 60
HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(HERE, ".posts.json")      # written by fetch.py, not committed
STORIES_PATH = os.path.join(HERE, ".stories.json")  # written by the refresh session, not committed


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def now_utc():
    return datetime.now(timezone.utc)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def log_x_scan(data_dir, status, message, duration_s=0, counts=None):
    """Append one x_scan entry to data/refresh_log.json."""
    path = os.path.join(data_dir, "refresh_log.json")
    entry = {"at": iso(now_utc()), "job": "x_scan", "status": status,
             "duration_s": round(duration_s), "message": message[:300], "counts": counts or {}}
    log = load_json(path, {})
    if log.get("sample"):
        log = {}  # drop placeholder entries on the first real run
    merged = sorted([entry] + log.get("entries", []), key=lambda e: e["at"], reverse=True)[:LOG_MAX]
    write_json(path, {"schema_version": 1, "generated_at": merged[0]["at"], "entries": merged})
