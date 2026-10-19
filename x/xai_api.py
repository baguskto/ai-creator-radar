"""Minimal xAI Responses API client for X Search (stdlib only).

Grok searches X on xAI's servers with the built-in x_search tool, so no X
developer account is needed. The API key is never stored in code or data. It
is read from the XAI_API_KEY environment variable when set; otherwise requests
go out without an Authorization header and rely on the environment's network
secret to add it.
"""

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.x.ai/v1/responses"
USD_PER_TICK = 1e-10  # usage.cost_in_usd_ticks


class XAIError(RuntimeError):
    pass


class XAIClient:
    def __init__(self, api_key=None, model="grok-4.7", timeout=300):
        self.api_key = api_key if api_key is not None else os.environ.get("XAI_API_KEY")
        self.model = model
        self.timeout = timeout
        self.requests = 0
        self.posts_fetched = 0
        self.cost_usd = 0.0

    def respond(self, body):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        self.requests += 1
        req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                err = json.load(e)
                msg = err.get("error") or err.get("message") or err
                msg = msg.get("message", msg) if isinstance(msg, dict) else msg
            except Exception:
                msg = str(e)
            # Never echo the request headers: they carry the key.
            raise XAIError(f"responses: HTTP {e.code}: {msg}") from None
        usage = data.get("usage") or {}
        tools = usage.get("server_side_tool_usage_details") or {}
        self.posts_fetched += tools.get("x_posts_fetched") or 0
        if usage.get("cost_usd") is not None:
            self.cost_usd += usage["cost_usd"]
        elif usage.get("cost_in_usd_ticks") is not None:
            self.cost_usd += usage["cost_in_usd_ticks"] * USD_PER_TICK
        return data

    # --- helpers -------------------------------------------------------

    def x_search(self, prompt, schema, from_date, max_turns=4):
        """One Grok request with X Search and a JSON schema. Returns (parsed JSON, cited URLs)."""
        data = self.respond({
            "model": self.model,
            "reasoning": {"effort": "low"},
            "max_turns": max_turns,
            "input": prompt,
            "tools": [{"type": "x_search", "from_date": from_date}],
            "text": {"format": {"type": "json_schema", "name": "posts", "schema": schema, "strict": True}},
        })
        text, cited = "", set(data.get("citations") or [])
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    text += part.get("text", "")
                for a in part.get("annotations") or []:
                    if a.get("type") == "url_citation" and a.get("url"):
                        cited.add(a["url"])
        try:
            return json.loads(text), cited
        except json.JSONDecodeError:
            raise XAIError(f"responses: no JSON in the answer ({data.get('status', 'unknown status')})") from None
