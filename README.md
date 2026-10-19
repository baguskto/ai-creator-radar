# AI Creator Radar

A static dashboard that spots AI stories taking off on X that YouTube hasn't covered yet, and turns each gap into ready-to-make content.

- `index.html`, `assets/`: the page (no build step). Served by GitHub Pages from `main`.
- `data/*.json`: what the page shows. Format: [docs/DATA.md](docs/DATA.md).
- `scripts/validate-data.mjs`: checks `data/` against the format. Run `node scripts/validate-data.mjs`.

Data is refreshed twice a day by one Claude cloud scheduled task: X trends (`x/`, Grok with xAI's X Search), then YouTube coverage, content packs, Claude Code news and channel stats. See [docs/REFRESH.md](docs/REFRESH.md). No keys or private data live in this repo.
