# Dashboard — Design & Build Plan

> Design-before-code doc for the WC2026 interactive dashboard (S40+).
> Live element-level tracker lives in Notion → **Dashboard Tracker**
> (under "🏆 World Cup 2026 Analytics Project"). This doc is the
> engineering record: stack, data contract, version ladder, repo layout.
> The Notion DB tracks *what* we build per element; this doc explains *how*.

## 1. Stack decision (S40)

**Streamlit first, web-app (FastAPI + JS) port later.** HTML artifact ruled out.

The deciding question was: does the dashboard need to **re-run the Python
model live**, or just display pre-computed output? The spec wants knobs,
player-swap and a sim button — all "change an input → recompute" — and that
recompute *is* our existing Python (occupancy boards → zone battles →
bivariate Poisson), reading DuckDB. That one fact drove the choice:

| Option | Live recompute | Interactivity ceiling | Lift | Verdict |
|---|---|---|---|---|
| **Streamlit** | ✅ imports the model directly | clickable tokens + dropdowns; drag-drop needs a custom component | low | **chosen for V0–V3** |
| Full web app (FastAPI + JS) | ✅ via an API layer | true drag-drop, polished UI | high (backend + frontend + API contract) | **later port** |
| Single-file HTML artifact | ❌ can't run Python | great SVG, but data must be baked in as JSON | low | **ruled out** (dead-end for live sim) |

Rationale for Streamlit-first: it's the only low-lift option that matches
"live recompute + Python + `uv` + DuckDB", and it's a genuine
data-engineering skill. The web-app is a *graduation* once the model logic
and UX are settled — porting a known-good Streamlit app to an API + frontend
is a cleaner second project than building the API blind.

## 2. Data contract (the model is already dashboard-ready)

Key finding (S40, observed in `src/load/v2_ingest/zone_aggregate.py`): the
model is **already factored into importable functions returning plain
dicts / numpy** — no model rewrite is needed. The seams the app calls:

| Function | Returns | Used for |
|---|---|---|
| `_scoreline_setup(formation)` | `(con, P)` — read-only DuckDB handle + all configs (`selection_scores`, `forwardness`, `zone_xt`, `volume`, …) | one-time heavy load |
| `_assemble_team(con, nation, cfg, fwd, scores, formation)` | `{nation, sid, boards, gk}` — auto-picked XI + attack/defence **occupancy boards** | XI + pitch view |
| `_lambda_pair(con, ta, tb, P)` | `(λ_A, λ_B)` | scoreline inputs |
| `bivariate_poisson_matrix(l1, l2, l3=0)` | 11×11 scoreline matrix | scoreline grid |
| `_matrix_summary(M)` | W/D/L, E[goals], most-likely score | result panel |

### Adapter seam (`dashboard/model_api.py`)

We do **not** call these private `_`-functions from the Streamlit view code
directly. A thin adapter module wraps them so the view stays presentation-only
and the swap/override logic has one home. The adapter closes the two known
gaps:

1. **Names.** `_assemble_team` keeps `ea_id`/`sid` but drops player *names*;
   `autopick_xi` has them. The adapter returns names alongside the board.
2. **Manual XI override.** `autopick_xi` always greedy-picks. The adapter
   accepts an optional `{slot_no: ea_id}` override so player-swap (V2) can
   replace one slot and reassemble. (The XI is already a `{slot_no: ea_id}`
   dict internally, so this is a passthrough, not new model logic.)

### Caching strategy

Streamlit re-runs the whole script top-to-bottom on every interaction, so the
heavy load must be cached or the app is unusable
([Streamlit caching](https://docs.streamlit.io/develop/concepts/architecture/caching)):

- **`@st.cache_resource`** on the setup (`P`) — keyed by `formation`. This is
  the expensive init (builds adjusted ratings, forwardness, zone_xt).
- **`@st.cache_data`** on per-team assembly — keyed by
  `(nation, formation, frozenset(xi_override.items()))` so a swap only
  recomputes the team that changed.

**Known caveat (flag for the web-app port):** a DuckDB connection is not
thread-safe, and `st.cache_resource` shares one object across browser
sessions/threads. Fine for V0 single-user local use; the web-app port will
need a connection-per-request (or a pool). For V0 we open the read-only
connection inside the cached setup and treat the app as single-user.

## 3. Version ladder

Each version is a vertical slice that runs end-to-end. Notion `Version`
property mirrors this exactly.

- **V0 — walking skeleton.** App boots; cached setup; pick nation A vs B
  (dropdowns) + formation; show both auto-XIs (text) + scoreline matrix +
  W/D/L/E[goals]. Proves the import/cache/contract end-to-end.
  *Elements: Match simulation (basic), Build approach.*
- **V1 — the pitch.** Formation pitch render + player tokens from the
  occupancy boards; click a token → right-side info panel.
  *Elements: Formation pitch, Player tokens, Right-side info panel.*
- **V2 — interactivity.** Player profile (EA + empirical toggle) + swap →
  recompute; knobs/filters (formation, λ₃, …).
  *Elements: Player profile, Player swap, Knobs / filters panel.*
- **V3 — outputs.** Dedicated stats view (occupancy heatmaps, zone-threat
  surface, scoreline-matrix viz) + fuller sim presentation.
  *Elements: Dedicated stats-view page, Match simulation (full).*
- **Then:** finalize the friend-proof README/setup manual; begin the
  web-app port.

## 4. Repo layout

```
dashboard/
  app.py          # Streamlit entry — view only (V0: pickers + scoreline)
  model_api.py    # adapter over zone_aggregate seams (names, XI override, caching)
  README.md       # friend-facing setup/run guide (grows each version)
```

- The app imports the model via `from src.load.v2_ingest...`, matching the
  existing package-absolute convention. Like `zone_aggregate.py`, it puts the
  repo root on `sys.path` so `streamlit run dashboard/app.py` resolves whether
  launched from root or elsewhere.
- **`uv add streamlit`** (project dep; not a tooling switch). Pitch/heatmap
  rendering library chosen at V1 (candidates: Plotly for hover/click, or
  matplotlib for static) — deferred until we see the board data shape.
- Read-only DB posture throughout — the dashboard never writes to
  `worldcup.duckdb`.

## 5. README / setup manual (friend-proof)

A first-class deliverable, grown per version, finalized before the web-app
port. Target: a friend clones the repo and runs the dashboard on their own
machine with no hand-holding. Must cover: prerequisites (WSL2/Python/`uv`),
clone, `uv sync`, the `soccerdata` overlay setup, where the `.duckdb` lives
(and how they obtain it — it's the data dependency), and the single run
command. Open question for V0 (see below): how a friend gets the DuckDB file.

## 6. Open questions (resolve as we hit them)

1. **DB distribution.** `worldcup.duckdb` is large and not in git. How does a
   friend get it — committed sample, release asset, regenerate script? (README
   blocker; decide at V0 close.)
2. **Pitch render library** — Plotly vs matplotlib vs custom SVG. Decide at V1
   when we can see the occupancy-board data shape.
3. **Drag-drop** — clickable-token swap for V2; revisit a custom drag-drop
   component only if clicking feels limiting (or defer to the web-app port).
4. **GK in the XI** — boards park the GK (no outfield board); the pitch view
   needs to place the GK token from `load_gk_score` separately.
```
