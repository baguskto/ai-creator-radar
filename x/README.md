# X scan

First step of the cloud refresh (`docs/REFRESH.md`). Finds the AI stories taking off on X and
writes `data/x_trends.json` per `docs/DATA.md`, in three steps, the middle one done by the refresh session:

1. `bash scripts/x-scan.sh` syncs `main` and runs `python3 x/fetch.py`: one Grok request per
   topic query with xAI's built-in X Search tool (`POST https://api.x.ai/v1/responses`), asking
   for up to 25 posts from the last day with 200+ likes. Writes `x/.posts.json` (not committed).
2. The session groups the posts into up to 15 stories in `x/.stories.json`
   (`x/CLUSTERING.md`): no extra LLM call, the session is Claude.
3. `python3 x/finish.py` checks the grouping, computes each story's metrics and heat from its
   posts, writes `data/x_trends.json` and logs an `x_scan` entry to `data/refresh_log.json`.

Stdlib Python 3, no installs, no X developer account. On any failure the previous
`data/x_trends.json` stays and the error is logged, so the page keeps the last good data.

**Key.** Never in code. Read from `XAI_API_KEY` if set; otherwise requests go out without an
`Authorization` header so the environment's network secret can add it.

**Queries.** `QUERIES` in `fetch.py`, each with `min_faves:200 -is:retweet -is:reply lang:en`.
X Search understands X's own search operators, so the likes filter runs on X's side.

**Trust.** Grok copies the posts into a JSON schema, and every post it got from X Search comes
with a citation. Posts it didn't cite are dropped, so a made-up post can't get through. A post's
time comes from its id (X ids encode it), not from Grok. Like, repost and view counts are the ones
Grok reads off the results; a missing like count is taken as 200, the query's minimum.

**Heat.** Per post, likes per hour since it was posted (age floored at 1 hour). A story's velocity
is the sum over its posts; `heat = 100 * log10(1 + velocity) / log10(1 + 5000)`, plus 5% per extra
author up to +20%, capped at 100.

**Cost.** xAI bills X Search per post fetched, plus tokens. Each run logs its cost
(`counts.cost_usd` and the message of the `x_scan` entry). `--max-turns` (default 4) bounds how
many rounds of searches one request can run; `--per-query` and `--model` tune the rest. A 401,
402, 403 or 429 (bad key, no credits or rate limit) stops further searches.

Tests: `python3 -m unittest discover -s x`
