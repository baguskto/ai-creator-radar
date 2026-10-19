"""Minimal X API v2 client (stdlib only).

The bearer token is never stored in code or data. It is read from the
X_BEARER_TOKEN environment variable when set; otherwise requests go out
without an Authorization header and rely on the environment's network
secret to add it.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.x.com/2/"

TWEET_FIELDS = "created_at,public_metrics,lang,author_id,note_tweet"
USER_FIELDS = "username,name,public_metrics"


class XError(RuntimeError):
    pass


class XClient:
    def __init__(self, token=None, timeout=30):
        self.token = token if token is not None else os.environ.get("X_BEARER_TOKEN")
        self.timeout = timeout
        self.requests = 0
        self.posts_read = 0

    def get(self, endpoint, **params):
        params = {k: v for k, v in params.items() if v is not None}
        url = API_ROOT + endpoint + "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.requests += 1
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                body = json.load(e)
                msg = body.get("detail") or body.get("title") or body["errors"][0]["message"]
            except Exception:
                msg = str(e)
            # Never echo the request headers: they may carry the token.
            raise XError(f"{endpoint}: HTTP {e.code}: {msg}") from None

    # --- helpers -------------------------------------------------------

    def search_recent(self, query, start_time, max_results=100):
        """One page of recent search, most relevant first. Returns (posts, users by id)."""
        data = self.get("tweets/search/recent", query=query, start_time=start_time,
                        max_results=max(10, min(100, max_results)), sort_order="relevancy",
                        expansions="author_id",
                        **{"tweet.fields": TWEET_FIELDS, "user.fields": USER_FIELDS})
        posts = data.get("data", [])
        self.posts_read += len(posts)
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        return posts, users
