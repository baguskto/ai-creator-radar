# AI Creator Radar data format

The dashboard is a static page that reads six JSON files from `data/`.
Each producer owns its file(s) and overwrites them in full on every run.
The page never computes data itself beyond simple fallbacks noted below.

| File | Producer | Runs |
| --- | --- | --- |
| `data/x_trends.json` | X scan (cloud refresh, `x/`) | twice daily, first step of the cloud refresh |
| `data/youtube_coverage.json` | YouTube coverage (cloud refresh) | twice daily, after the X scan lands |
| `data/channel_stats.json` | Channel stats (cloud refresh) | twice daily |
| `data/content_packs.json` | Content packs (cloud refresh) | twice daily, after coverage |
| `data/claude_code_news.json` | Claude Code news (cloud refresh) | twice daily |
| `data/refresh_log.json` | every job appends one entry | every run |

## Rules for every file

- UTF-8 JSON, 2-space indent, no comments.
- Every file has `"schema_version": 1` and `"generated_at"` (ISO 8601 UTC, e.g. `2026-10-16T13:00:00Z`).
- `"sample": true` marks placeholder data. Producers write `"sample": false` (or omit it). The page shows a SAMPLE tag on any panel whose file is sample data.
- The repo is public. No API keys, cookies, tokens, emails, or anything from a private account. Public post URLs, handles and public counts are fine.
- Story ids are the join key across files: lowercase kebab-case slugs, stable across runs for the same story where possible (e.g. `openai-o5-launch`). `x_trends.json` mints them; other files reference them as `story_id`.
- Keep files small: at most 15 stories, 10 videos per story, 60 log entries.
- Unknown extra fields are allowed and ignored by the page, so producers can add fields without breaking it. Renaming or removing a field below is a schema change: send it through the coordinator so the page is updated with it.

## Publishing

All jobs commit straight to `main` (GitHub Pages serves `main`), touching only their own files:

```
git pull --rebase origin main
# write your file(s), append your refresh_log entry
git add data/<your files> data/refresh_log.json
git commit -m "data: <job> refresh <generated_at>"
git push origin main   # on rejection: pull --rebase and retry, up to 4 times
```

Validate before committing: `node scripts/validate-data.mjs` (no dependencies).

---

## `x_trends.json`

Stories taking off on X right now. Sorted by `heat`, highest first.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T12:30:00Z",
  "sample": false,
  "window_hours": 24,
  "queries": ["claude", "openai", "gemini"],
  "stories": [
    {
      "id": "openai-o5-launch",
      "title": "OpenAI ships o5 with native computer use",
      "summary": "One or two sentences on what happened.",
      "keywords": ["o5", "openai", "computer use"],
      "first_seen": "2026-10-16T06:10:00Z",
      "heat": 92,
      "metrics": {
        "posts": 1840,
        "likes": 212000,
        "reposts": 31000,
        "views": 18400000,
        "velocity_per_hour": 140
      },
      "top_posts": [
        {
          "url": "https://x.com/someone/status/123",
          "author": "@someone",
          "text": "Post text, trimmed to 280 chars.",
          "likes": 12000,
          "reposts": 2100,
          "posted_at": "2026-10-16T07:02:00Z"
        }
      ]
    }
  ]
}
```

- `heat` (required): 0 to 100, how hard the story is taking off on X. The scanner decides the formula; it should mostly reflect engagement velocity.
- `metrics.*`, `top_posts`, `summary`, `keywords`, `first_seen` are optional but strongly wanted. `top_posts` max 3.

## `youtube_coverage.json`

How much YouTube already covers each X story.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T13:00:00Z",
  "x_trends_generated_at": "2026-10-16T12:30:00Z",
  "lookback_hours": 72,
  "stories": [
    {
      "story_id": "openai-o5-launch",
      "query": "openai o5",
      "video_count": 2,
      "total_views": 41000,
      "coverage": "low",
      "gap_score": 81,
      "top_videos": [
        {
          "video_id": "abc123",
          "title": "Video title",
          "channel": "Channel name",
          "published_at": "2026-10-16T09:00:00Z",
          "views": 30000,
          "url": "https://www.youtube.com/watch?v=abc123"
        }
      ]
    }
  ]
}
```

- `video_count`: videos matching the story published within `lookback_hours`.
- `coverage`: `"none"` (0 videos), `"low"`, `"medium"`, `"high"`. Producer picks thresholds.
- `gap_score` (0 to 100): big on X, thin on YouTube. Suggested formula, producer may refine:
  `round(heat * 1 / (1 + video_count / 3) * (total_views > 500000 ? 0.6 : 1))`.
  If missing, the page falls back to `round(heat / (1 + video_count / 3))`.
- `x_trends_generated_at`: the `generated_at` of the X file this run was computed against.

## `content_packs.json`

Ready-to-make content for the top gaps (up to 5), in gap order.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T13:10:00Z",
  "packs": [
    {
      "story_id": "openai-o5-launch",
      "video": {
        "title": "OpenAI o5 Just Changed Computer Use Forever",
        "thumbnail_text": "IT USES YOUR PC",
        "hook": "First 15 seconds of the video, as spoken."
      },
      "short": {
        "duration_s": 30,
        "beats": [
          { "t": "0-3s", "line": "Spoken line", "visual": "What is on screen" }
        ]
      },
      "carousel": {
        "slides": [
          { "heading": "Slide headline", "body": "One or two short lines." }
        ]
      },
      "x_post": "Text of the X post, 280 chars max."
    }
  ]
}
```

- `short.beats`: in order, covering about 30 seconds. `visual` optional.
- `carousel.slides`: 5 to 8 slides. The first slide is the cover, the last is the call to action. The page renders each slide as a square preview card.

## `claude_code_news.json`

Claude Code release news, newest first.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T13:00:00Z",
  "latest_version": "2.4.1",
  "items": [
    {
      "version": "2.4.1",
      "date": "2026-10-15",
      "title": "Short headline for the release",
      "highlights": ["Up to 5 bullet points, one line each."],
      "url": "https://github.com/anthropics/claude-code/releases/tag/v2.4.1",
      "creator_angle": "Optional: one line on why this is worth a video."
    }
  ]
}
```

At most 8 items.

## `channel_stats.json`

Chase AI (@Chase-H-AI) public channel stats and how the newest videos compare to the usual.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T13:00:00Z",
  "channel": {
    "id": "UC...",
    "title": "Chase AI",
    "handle": "@Chase-H-AI",
    "subscribers": 120000,
    "total_views": 9800000,
    "video_count": 310
  },
  "baseline": {
    "description": "Median of the 20 videos before the latest 5, measured at the same age",
    "median_views": 24000,
    "median_views_per_day": 3400
  },
  "recent_videos": [
    {
      "video_id": "xyz",
      "title": "Video title",
      "published_at": "2026-10-14T15:00:00Z",
      "url": "https://www.youtube.com/watch?v=xyz",
      "views": 41000,
      "likes": 2100,
      "comments": 310,
      "views_per_day": 20500,
      "vs_baseline": 1.7
    }
  ]
}
```

- `recent_videos`: the latest 5 to 8 uploads, newest first.
- `vs_baseline`: this video's performance divided by the baseline (1.0 is usual, 2.0 is double). The producer decides how to age-adjust and says how in `baseline.description`.

## `refresh_log.json`

One entry per job run, newest first, capped at 60 entries.

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-16T13:12:00Z",
  "entries": [
    {
      "at": "2026-10-16T13:12:00Z",
      "job": "cloud_refresh",
      "step": "youtube_coverage",
      "status": "ok",
      "duration_s": 42,
      "message": "Checked 12 stories, 3 gaps",
      "counts": { "stories": 12 }
    }
  ]
}
```

- `job`: `"x_scan"` (the X scan) or `"cloud_refresh"` (everything after it).
- `step`: optional, which part of the job (`youtube_coverage`, `channel_stats`, `content_packs`, `claude_code_news`).
- `status`: `"ok"`, `"partial"`, or `"error"`. On error, keep the previous data file and log the error, so the page keeps showing the last good data.
- Set top-level `generated_at` to the newest entry's `at`.
