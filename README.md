# AI Creator Radar

A static dashboard that spots AI stories taking off on X that YouTube hasn't covered yet, and turns each gap into ready-to-make content.

- `index.html`, `assets/`: the page (no build step). Served by GitHub Pages from `main`.
- `data/*.json`: what the page shows. Format: [docs/DATA.md](docs/DATA.md).
- `scripts/validate-data.mjs`: checks `data/` against the format. Run `node scripts/validate-data.mjs`.

Data is refreshed twice a day: X trends from a local job, then YouTube coverage, content packs, Claude Code news and channel stats from a cloud refresh. No keys or private data live in this repo.
