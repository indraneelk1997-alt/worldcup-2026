# WC2026 Match Simulator — Dashboard

An interactive Streamlit app on top of a from-scratch football match model
("the chessboard"): pick any two of the 48 World Cup 2026 nations and it builds
each side's best XI, plays the matchup through the model, and shows the
simulated scoreline — win/draw/loss odds, most-likely result, and the full
score-probability grid.

> **Status: V0 (walking skeleton).** Two nations → XIs + scoreline. The
> interactive pitch, player swaps, knobs and stats views land in later versions.

## What you need

- **Linux, macOS, or Windows + WSL2** (the project is developed on WSL2/Ubuntu).
- **Python 3.12**.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — the package/environment manager this project uses. One-line install on the uv site.
- **git**.

You do **not** need any API keys, scrapers, or a data download — the data the
dashboard reads ships inside the repo (a trimmed 17 MB DuckDB file).

## Setup

```bash
# 1. clone
git clone <repo-url> worldcup-2026
cd worldcup-2026

# 2. install dependencies into a local .venv (uv reads pyproject.toml / uv.lock)
uv sync

# 3. run the dashboard
uv run streamlit run dashboard/app.py
```

Streamlit prints a local URL (default <http://localhost:8501>) and opens it in
your browser. Pick two nations from the dropdowns and the result updates.

## How it finds its data

The app reads `data/processed/worldcup_dashboard.duckdb` — the trimmed,
read-only database that's committed with the repo, so a plain clone just works.
It's auto-detected; you don't have to configure anything.

To point the app at a different database (e.g. a full local build), set an
environment variable for the run:

```bash
WC2026_DB=/path/to/other.duckdb uv run streamlit run dashboard/app.py
```

## What's under the hood

- `dashboard/app.py` — the Streamlit view (presentation only).
- `dashboard/model_api.py` — a thin adapter over the model; the app calls only
  this, never the model internals.
- The model itself lives in `src/load/v2_ingest/` and is documented in `docs/`
  (`dashboard_design.md` for the dashboard architecture, `item8_aggregation.md`
  for the match engine).

## Rebuilding the trimmed database (maintainer)

The committed DB is produced from the full ~950 MB project database by dropping
the three large StatsBomb raw tables (which the dashboard never reads):

```bash
uv run python src/tools/make_dashboard_db.py
```

That writes `data/processed/worldcup_dashboard.duckdb` (~17 MB). Re-run it
whenever the model's underlying tables change.
