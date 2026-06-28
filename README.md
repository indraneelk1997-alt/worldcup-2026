# worldcup-2026

A World Cup 2026 match-simulation model + interactive dashboard. Player ratings
blend EA FC26 attributes with empirical performance data; a zone-based ("chessboard")
model turns squads into occupancy boards → zone battles → a bivariate-Poisson
scoreline. The Streamlit dashboard lets you pick two nations, tweak formations and
XIs, and read the resulting matchup, plus inspect squad coverage and the ratings
pipeline.

## Run the dashboard

You only need **read access** to this repo — the dashboard is self-contained. It
runs off the committed, trimmed database (`data/processed/worldcup_dashboard.duckdb`,
~18 MB); you do **not** need the full database or any of the data pipeline.

**Prerequisites:** [`git`](https://git-scm.com/) and
[`uv`](https://docs.astral.sh/uv/) (which manages Python 3.12+ and all deps).

```bash
git clone https://github.com/indraneelk1997-alt/worldcup-2026.git
cd worldcup-2026
uv sync                                   # installs Python + dependencies
uv run streamlit run dashboard/app.py     # opens at http://localhost:8501
```

That's it. The app auto-detects the committed dashboard DB, so there's nothing to
configure.

### Sections (sidebar)

- **Match simulator** — pick Team A / B, view the formation pitch (click a player
  for their profile + kernel), the two-team playstyle radar, and the scoreline.
- **Squad coverage** — how much real data backs each nation's squad.
- **Ratings audit** — per player, how the EA rating was blended toward empirical
  performance (EA pct vs empirical pct, λ, and the raw → adjusted attributes).

### Notes

- If a friend has the full `worldcup.duckdb` locally and wants to use it instead,
  set `WC2026_DB=data/processed/worldcup.duckdb` before running. Otherwise ignore.
- Read-only is sufficient: collaborators need only the GitHub **Read** role (or
  nothing, if the repo is public). No push access required to run anything.
