"""Offline tests: python3 -m unittest discover -s x"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch  # noqa: E402
import finish  # noqa: E402
from x_api import XError  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def tweet(id, likes, hours_ago=2, author="u1", text="hello", **extra):
    return {"id": id, "author_id": author, "created_at": ts(hours_ago), "text": text,
            "public_metrics": {"like_count": likes, "retweet_count": likes // 10, "reply_count": 1,
                               "quote_count": 0, "impression_count": likes * 100}, **extra}


USERS = {"u1": {"id": "u1", "username": "alice", "public_metrics": {"followers_count": 5000}},
         "u2": {"id": "u2", "username": "bob", "public_metrics": {"followers_count": 10}}}


class FakeClient:
    """Answers recent search from canned results, one list per query in order."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.posts_read = 0
        self.queries = []

    def search_recent(self, query, start_time, max_results=100):
        self.queries.append((query, start_time, max_results))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        self.posts_read += len(page)
        return page, USERS


def post(id, likes, author="@alice", hours_ago=2, views=1000):
    return {"id": id, "url": f"https://x.com/{author[1:]}/status/{id}", "author": author,
            "text": f"post {id}", "likes": likes, "reposts": likes // 10, "views": views,
            "posted_at": ts(hours_ago).replace(".000", ""), "velocity_per_hour": likes / hours_ago}


class FetchTest(unittest.TestCase):
    def test_normalize(self):
        t = tweet("1", 500, hours_ago=4, text="short &amp; cut", note_tweet={"text": "long &amp; full"})
        p = fetch.normalize(t, USERS, NOW)
        self.assertEqual(p["url"], "https://x.com/alice/status/1")
        self.assertEqual(p["author"], "@alice")
        self.assertEqual(p["text"], "long & full")
        self.assertEqual(p["views"], 50000)
        self.assertEqual(p["posted_at"], "2026-10-16T08:00:00Z")
        self.assertEqual(p["velocity_per_hour"], 125.0)

    def test_normalize_unknown_author_and_young_post(self):
        p = fetch.normalize(tweet("2", 300, hours_ago=0.1, author="nobody"), USERS, NOW)
        self.assertEqual(p["url"], "https://x.com/i/status/2")
        self.assertEqual(p["velocity_per_hour"], 300.0)  # age floored at 1 hour

    def test_run_filters_dedupes_and_sorts(self):
        client = FakeClient([[tweet("1", 250), tweet("2", 150)], [tweet("1", 250), tweet("3", 900, author="u2")]])
        posts, ok, errors = fetch.run(client, ["q1", "q2"], NOW, window_hours=24, min_likes=200)
        self.assertEqual([p["id"] for p in posts], ["3", "1"])
        self.assertEqual(posts[1]["queries"], [1, 2])
        self.assertEqual((ok, errors), (2, []))
        self.assertEqual(client.queries[0][1], "2026-10-15T12:00:00Z")

    def test_run_stops_on_auth_error(self):
        client = FakeClient([XError("tweets/search/recent: HTTP 401: Unauthorized"), [tweet("1", 999)]])
        posts, ok, errors = fetch.run(client, ["q1", "q2"], NOW)
        self.assertEqual((posts, ok, len(errors)), ([], 0, 1))
        self.assertEqual(len(client.queries), 1)

    def test_run_continues_after_other_errors(self):
        client = FakeClient([XError("tweets/search/recent: HTTP 503: busy"), [tweet("1", 999)]])
        posts, ok, errors = fetch.run(client, ["q1", "q2"], NOW)
        self.assertEqual(([p["id"] for p in posts], ok, len(errors)), (["1"], 1, 1))


class FinishTest(unittest.TestCase):
    POSTS = {p["id"]: p for p in [post("1", 3000), post("2", 400, author="@bob"), post("3", 250)]}

    def story(self, id="a-story", ids=("1",), **kw):
        return {"id": id, "title": "Something happened", "summary": "It happened.",
                "keywords": ["thing", "happened"], "post_ids": list(ids), **kw}

    def test_check_accepts_valid(self):
        self.assertEqual(finish.check({"stories": [self.story(ids=("1", "2")), self.story("b", ("3",))]},
                                      self.POSTS), [])

    def test_check_catches_problems(self):
        doc = {"stories": [self.story("Bad Id"), self.story("a", ("1", "9")), self.story("b", ("1",)),
                           self.story("a", ("2",), keywords=["one"])]}
        problems = "\n".join(finish.check(doc, self.POSTS))
        self.assertIn("kebab-case", problems)
        self.assertIn("post 9 is not in", problems)
        self.assertIn("post 1 is already in a", problems)
        self.assertIn("duplicate id", problems)
        self.assertIn("keywords", problems)
        self.assertIn("max 15", "\n".join(finish.check({"stories": [self.story(f"s{i}") for i in range(16)]}, {})))

    def test_heat(self):
        self.assertEqual(finish.heat(0, 1), 0)
        self.assertEqual(finish.heat(5000, 1), 100)
        self.assertLess(finish.heat(100, 1), finish.heat(100, 3))
        self.assertEqual(finish.heat(1e9, 9), 100)

    def test_build(self):
        many = {**self.POSTS, "4": post("4", 220, views=None)}
        out = finish.build([self.story("small", ("3",)), self.story("big", ("4", "2", "1"))], many)
        self.assertEqual([s["id"] for s in out], ["big", "small"])
        big = out[0]
        self.assertEqual([p["author"] for p in big["top_posts"]], ["@alice", "@bob", "@alice"])
        self.assertEqual(big["metrics"]["posts"], 3)
        self.assertEqual(big["metrics"]["likes"], 3620)
        self.assertEqual(big["metrics"]["views"], 2000)  # the post without views is skipped
        self.assertEqual(big["first_seen"], "2026-10-16T10:00:00Z")

    def test_trim(self):
        self.assertEqual(len(finish.trim("x" * 400)), 280)
        self.assertEqual(finish.trim("short"), "short")


class EndToEndTest(unittest.TestCase):
    def test_finish_writes_trends_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            posts_path, stories_path = os.path.join(d, ".posts.json"), os.path.join(d, ".stories.json")
            data = os.path.join(d, "data")
            with open(posts_path, "w") as f:
                json.dump({"fetched_at": "2026-10-16T12:00:00Z", "duration_s": 3, "window_hours": 24,
                           "min_likes": 200, "queries": ["q1"], "searches_ok": 1, "errors": [],
                           "posts_read": 100, "previous_stories": [], "posts": [post("1", 3000)]}, f)
            with open(stories_path, "w") as f:
                json.dump({"stories": [FinishTest().story()]}, f)
            old = finish.POSTS_PATH, finish.STORIES_PATH
            finish.POSTS_PATH, finish.STORIES_PATH = posts_path, stories_path
            try:
                self.assertEqual(finish.main(["--data", data]), 0)
            finally:
                finish.POSTS_PATH, finish.STORIES_PATH = old
            with open(os.path.join(data, "x_trends.json")) as f:
                trends = json.load(f)
            with open(os.path.join(data, "refresh_log.json")) as f:
                log = json.load(f)
            self.assertEqual(trends["generated_at"], "2026-10-16T12:00:00Z")
            self.assertEqual(trends["stories"][0]["id"], "a-story")
            self.assertFalse(trends["sample"])
            self.assertEqual(log["entries"][0]["job"], "x_scan")
            self.assertEqual(log["entries"][0]["message"], "1 stories from 1 posts across 1 searches")


if __name__ == "__main__":
    unittest.main()
