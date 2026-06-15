# Run the WC2026 Match Simulator dashboard

Everything needed to run the dashboard is in the repo — including a committed
**17.6 MB trimmed DuckDB** (`data/processed/worldcup_dashboard.duckdb`). So there
is **no data download and no database build**: clone, sync deps, run.

## Prerequisites
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.12 is
  fetched by uv automatically).
- git (you have collaborator access to `indraneelk1997-alt/worldcup-2026`).

## Run it

```bash
# first time
git clone https://github.com/indraneelk1997-alt/worldcup-2026.git
cd worldcup-2026

# or if you already have it
# cd worldcup-2026 && git checkout main && git pull

uv sync                                  # installs locked deps (streamlit, duckdb, scipy, plotly)
uv run streamlit run dashboard/app.py    # opens http://localhost:8501
```

That's it. The app auto-uses the committed trimmed DB (`model_api` defaults
`WC2026_DB` to it when present), so what you see is exactly what runs here.

## What to look at (the new stuff, S42)
- **Position-aware XI** — players are slotted by where they actually play
  (empirical minutes across Understat + FBref + StatsBomb, with EA fallback), not
  just by coarse group. Pick ESP/ENG and note Cucurella at LB, Kane at ST, etc.
- **Formation knob** (info panel, first control) — defaults to the auto best-fit
  shape for the squad; change the dropdown and the pitch + playstyle axes
  reassemble.
- **Player swap** — *Substitutes / swap a player* expander: replace any starter
  with an eligible alternative; the scoreline recomputes live.

## Optional sanity checks (no Streamlit)

```bash
uv run python dashboard/model_api.py ESP ENG                         # adapter self-test
uv run python -m src.load.v2_ingest.zone_aggregate --autoxi          # XIs across nations
uv run python -m src.load.v2_ingest.zone_aggregate --best-formation  # auto formation per nation
```

> Note: the `--autoxi` / `--best-formation` probes read the **full** DB by default.
> Against the committed trimmed DB, prepend `WC2026_DB=data/processed/worldcup_dashboard.duckdb`
> and `PYTHONPATH=src/load/v2_ingest` (some model probes use bare sibling imports).

## Context (for an AI assistant reading this repo)
- `Claude.md` — project conventions/environment. `docs/session_state.md` — current
  state (read the top + the S42 entries). `docs/item9_xi_selection.md` — the design
  of the selection/formation work.
- The dashboard talks to the model only through `dashboard/model_api.py` (a
  Streamlit-agnostic adapter); the model lives in `src/load/v2_ingest/`.
