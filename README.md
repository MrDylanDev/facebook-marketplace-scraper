# facebook-marketplace-scraper

> **Ethics notice:** this is an educational portfolio demo. Scrape only public
> data or accounts you own, respect each site's Terms of Service and rate
> limits, and never commit credentials (`auth_state.json`, `.env`). CI never
> touches live Facebook — fixture fallback only. Read [DISCLAIMER](./DISCLAIMER)
> before running the Facebook module.

Dual-track marketplace scraper: **MercadoLibre public API** (primary, CI-safe)
plus an **opt-in Facebook Playwright module** (`--target facebook`) with gentle
defaults and a recorded-fixture fallback. Both targets sit behind one
`MarketplaceAdapter` protocol and export to CSV, SQLite, or JSON.

- Facebook Terms of Service: <https://www.facebook.com/terms.php>
- MercadoLibre developer portal and API terms: <https://developers.mercadolibre.com/>

## Install

Requires Python 3.14+.

```bash
pip install -e ".[dev]"        # lint + tests
pip install -e ".[facebook]"   # opt-in: Playwright for live Facebook runs
python -m playwright install chromium  # only for live Facebook runs
```

## Quickstart

```bash
# MercadoLibre (public API, no auth needed)
python -m src.cli --target mercadolibre --query "bici rodado 29" --limit 10

# Facebook via recorded fixture (default in CI, no browser needed)
FB_FIXTURE=1 python -m src.cli --target facebook --query bici --limit 2

# Export to CSV / JSON / SQLite (extension decides the format)
FB_FIXTURE=1 python -m src.cli --target facebook --query bici --limit 5 --out results.csv
python -m src.cli --target mercadolibre --query bici --limit 5 --out results.json
python -m src.cli --target mercadolibre --query bici --limit 5 --out results.sqlite
```

## Targets

| Target | Auth | Notes |
|--------|------|-------|
| `mercadolibre` (alias `mercado-libre`) | None — public REST API | Pagination + exponential backoff with jitter on HTTP 429. |
| `facebook` | Manual one-time login → local `auth_state.json` (never committed), or fixture mode | Gentle limits (`N` clamped to 1–60), bounded scroll passes, login-wall/checkpoint abort, transient-error backoff. Without `auth_state.json` (or with `FB_FIXTURE=1`) serves the recorded fixture — this is what CI uses. |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `FB_FIXTURE=1` | Force the recorded fixture instead of a live Facebook run. |
| `FB_FIXTURE_PATH` | Override the fixture file (default `tests/fixtures/fb_listings.json`). |
| `FB_AUTH_STATE` | Override the `auth_state.json` location (manual login round-trip). |

To create `auth_state.json`, run the manual login helper once in a browser you
control, then keep the file local — it is git-ignored and rejected by CI if
tracked (see [CONTRIBUTING](./CONTRIBUTING)).

## Export formats

| Extension | Writer |
|-----------|--------|
| `.csv` | Streaming `csv.DictWriter` |
| `.json` | Incremental top-level array (never fully materialized) |
| `.db` / `.sqlite` / `.sqlite3` | `listings` table, `INSERT OR REPLACE` |

Unknown extensions exit non-zero (`rc=2`) with the supported list.

## Testing

```bash
python -m pytest tests/ -v          # full suite (41 tests, fixtures/mocks only)
xvfb-run -a python -m pytest tests/ # headless, as CI does
ruff check src tests                # lint
ruff format --check src tests       # format
```

Conventions: MercadoLibre adapter tests use mocked HTTP (live API is never
required); Facebook tests use the recorded fixture and prove the lazy-import
path works with Playwright uninstalled; any live-Facebook test must be marked
to skip in CI. CI (`.github/workflows/ci.yml`) runs Ruff, pytest under
`xvfb-run`, and a secret scan (gitleaks over full history + a tracked-credentials
assertion).

## Docker

```bash
docker build -t marketplace-scraper .
# Fixture demo (default: FB_FIXTURE=1 baked in)
docker run --rm marketplace-scraper --target facebook --query bici --limit 2
# Live Facebook: override fixture mode and mount your own state file
docker run --rm -e FB_FIXTURE=0 -v "$PWD/auth_state.json:/app/auth_state.json:ro" \
  marketplace-scraper --target facebook --query bici --limit 5
```

The image is `python:3.14-slim` based, installs Playwright Chromium with system
deps, and runs as a non-root `appuser`.

## Project layout

```text
src/
  models/listing.py        # shared Pydantic Listing schema
  adapters/base.py         # MarketplaceAdapter protocol
  adapters/mercado_libre.py# public API adapter (httpx, 429 backoff)
  adapters/facebook.py     # Playwright module + FixtureLoader
  exporters/               # csv / json / sqlite streaming writers
  cli.py                   # argparse entry point (marketplace-scraper)
tests/                     # pytest suite + tests/fixtures/fb_listings.json
.github/workflows/ci.yml   # ruff + pytest(xvfb) + secret scan
Dockerfile / .dockerignore
DISCLAIMER / CONTRIBUTING / LICENSE (MIT)
```

## Contributing, license, disclaimer

- [CONTRIBUTING](./CONTRIBUTING) — setup, fixture-first rule, no-credentials policy.
- [DISCLAIMER](./DISCLAIMER) — educational use, ToS compliance, no warranty.
- [LICENSE](./LICENSE) — MIT.
