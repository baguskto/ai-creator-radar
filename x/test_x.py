"""Offline tests: python3 -m unittest discover -s x"""

import json
import os
import sys
import io
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch  # noqa: E402
import finish  # noqa: E402
import xai_api  # noqa: E402
from xai_api import XAIError  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sid(hours_ago):
    """A post id (snowflake) for a post made hours_ago before NOW."""
    ms = int((NOW - timedelta(hours=hours_ago)).timestamp() * 1000)
    return str((ms - fetch.X_EPOCH_MS) << 22)


def raw(id, likes=500, handle="alice", **kw):
    return {"url": f"https://x.com/{handle}/status/{id}", "username": handle, "text": " hi ",
            "likes": likes, "reposts": 7, "views": 9000, **kw}


class FakeClient:
    """Answers X Search requests from canned (answer, cited URLs) pairs, one per query in order."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def x_search(self, prompt, schema, from_date, max_turns=4):
        self.calls.append((prompt, from_date))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        posts = page
        return {"posts": posts}, {p["url"] for p in posts if not p.get("uncited")}


def post(id, likes, author="@alice", hours_ago=2, views=1000):
    return {"id": id, "url": f"https://x.com/{author[1:]}/status/{id}", "author": author,
            "text": f"post {id}", "likes": likes, "reposts": likes // 10, "views": views,
            "posted_at": ts(hours_ago), "velocity_per_hour": likes / hours_ago}


class FetchTest(unittest.TestCase):
    def test_posted_time_from_snowflake(self):
        self.assertEqual(fetch.iso(fetch.posted_time("2110852716247519517")), "2026-10-15T21:57:59Z")

    def test_normalize(self):
        pid = sid(4)
        p = fetch.normalize(raw(pid, likes=1000), {pid}, NOW, 200)
        self.assertEqual(p["url"], f"https://x.com/alice/status/{pid}")
        self.assertEqual((p["author"], p["text"], p["reposts"], p["views"]), ("@alice", "hi", 7, 9000))
        self.assertEqual(p["posted_at"], ts(4))
        self.assertEqual(p["velocity_per_hour"], 250.0)

    def test_normalize_drops_uncited_and_fills_gaps(self):
        pid = sid(0.1)
        self.assertIsNone(fetch.normalize(raw(pid), set(), NOW, 200))
        p = fetch.normalize({"url": f"https://x.com/i/status/{pid}", "username": "@bob", "text": "t",
                             "likes": None, "reposts": None, "views": None}, {pid}, NOW, 200)
        self.assertEqual((p["author"], p["likes"], p["reposts"], p["views"]), ("@bob", 200, 0, None))
        self.assertEqual(p["velocity_per_hour"], 200.0)  # age floored at 1 hour
        self.assertEqual(fetch.normalize(raw(pid, likes=50), {pid}, NOW, 200)["likes"], 200)

    def test_run_dedupes_filters_and_sorts(self):
        a, b, old = sid(2), sid(3), sid(30)
        client = FakeClient([[raw(a, 300), {**raw(sid(1)), "uncited": True}, raw(old, 9999)],
                             [raw(a, 300), raw(b, 900, handle="bob")]])
        posts, ok, errors, dropped = fetch.run(client, ["q1", "q2"], NOW, window_hours=24)
        self.assertEqual([p["id"] for p in posts], [b, a])
        self.assertEqual(posts[1]["queries"], [1, 2])
        self.assertEqual((ok, errors, dropped), (2, [], 1))
        self.assertEqual(client.calls[0][1], "2026-10-15")
        self.assertIn("q1", client.calls[0][0])

    def test_run_stops_on_auth_error(self):
        client = FakeClient([XAIError("responses: HTTP 401: bad key"), [raw(sid(1))]])
        posts, ok, errors, _ = fetch.run(client, ["q1", "q2"], NOW)
        self.assertEqual((posts, ok, len(errors)), ([], 0, 1))
        self.assertEqual(len(client.calls), 1)

    def test_run_continues_after_other_errors(self):
        pid = sid(1)
        client = FakeClient([XAIError("responses: HTTP 503: busy"), [raw(pid)]])
        posts, ok, errors, _ = fetch.run(client, ["q1", "q2"], NOW)
        self.assertEqual(([p["id"] for p in posts], ok, len(errors)), ([pid], 1, 1))


class XAIClientTest(unittest.TestCase):
    RESPONSE = {
        "status": "completed",
        "output": [
            {"type": "x_search_call", "status": "completed"},
            {"type": "message", "content": [{
                "type": "output_text", "text": '{"posts": []}',
                "annotations": [{"type": "url_citation", "url": "https://x.com/a/status/1"}]}]},
        ],
        "usage": {"cost_in_usd_ticks": 1234500000, "server_side_tool_usage_details": {"x_posts_fetched": 20}},
    }

    def test_x_search_parses_answer_citations_and_usage(self):
        client = xai_api.XAIClient(api_key="test")
        with mock.patch.object(xai_api.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(self.RESPONSE).encode())) as urlopen:
            answer, cited = client.x_search("prompt", {"type": "object"}, "2026-10-15")
        body = json.loads(urlopen.call_args[0][0].data)
        self.assertEqual(body["tools"], [{"type": "x_search", "from_date": "2026-10-15"}])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertEqual(urlopen.call_args[0][0].get_header("Authorization"), "Bearer test")
        self.assertEqual((answer, cited), ({"posts": []}, {"https://x.com/a/status/1"}))
        self.assertEqual(client.posts_fetched, 20)
        self.assertAlmostEqual(client.cost_usd, 0.12345)

    def test_x_search_without_json_raises(self):
        bad = {"status": "incomplete", "output": []}
        with mock.patch.object(xai_api.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(bad).encode())):
            with self.assertRaises(XAIError):
                xai_api.XAIClient(api_key="").x_search("p", {}, "2026-10-15")


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
                           "posts_fetched": 40, "cost_usd": 0.31, "previous_stories": [],
                           "posts": [post("1", 3000)]}, f)
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
            self.assertEqual(log["entries"][0]["message"], "1 stories from 1 posts across 1 searches (xAI $0.31)")
            self.assertEqual(log["entries"][0]["counts"]["cost_usd"], 0.31)


if __name__ == "__main__":
    unittest.main()
