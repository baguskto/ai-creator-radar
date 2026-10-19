# X scan

First step of the cloud refresh (`docs/REFRESH.md`). Finds the AI stories taking off on X and
writes `data/x_trends.json` per `docs/DATA.md`, in three steps, the middle one done by the refresh session:

1. `bash scripts/x-scan.sh` syncs `main` and runs `python3 x/fetch.py`: one
   X API v2 recent search (`GET /2/tweets/search/recent`) per topic query
   over the last 24 hours, most relevant first, keeping posts with 200+ likes. Writes
   `x/.posts.json` (not committed).
2. The session groups the posts into up to 15 stories in `x/.stories.json`
   (`x/CLUSTERING.md`): no LLM API key, the session is Claude.
3. `python3 x/finish.py` checks the grouping, computes each story's metrics and heat from its
   posts, writes `data/x_trends.json` and logs an `x_scan` entry to `data/refresh_log.json`.

Stdlib Python 3, no installs. On any failure the previous `data/x_trends.json` stays and the
error is logged, so the page keeps the last good data.

**Token.** Never in code. Read from `X_BEARER_TOKEN` if set; otherwise requests go out without an
`Authorization` header so the environment's network secret can add it.

**Queries.** `QUERIES` in `fetch.py`, each with `lang:en -is:reply -is:retweet`. The X API has no
likes filter (the web search's `min_faves:` is not available), so `--min-likes` is applied after
the search.

**Heat.** Per post, likes per hour since it was posted (age floored at 1 hour). A story's velocity
is the sum over its posts; `heat = 100 * log10(1 + velocity) / log10(1 + 5000)`, plus 5% per extra
author up to +20%, capped at 100.

**Usage.** Up to `--max-results` (default 100) posts read per search, 5 searches per run. A 401,
402, 403 or 429 (bad token, plan or rate limit) stops further searches.

Tests: `python3 -m unittest discover -s x`
