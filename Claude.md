# World Cup 2026 Simulator — Project Context

> **Canonical project reference.** Read this first in every session.
> Slow-changing facts only (environment, rules, gotchas). For "where we
> are right now," read `docs/session_state.md`. For schema, read
> `docs/db_schema.md`.

## What this is

A football match simulator built toward FIFA World Cup 2026. Built
incrementally across sessions, primarily as a vehicle for the maintainer
to learn data engineering, DuckDB, and structured software practice.

**Maintainer profile:** sustainability + industrial engineering
professional, ~4 yrs consulting, MSc sustainable production. Comfortable
with base coding, WSL2, VS Code, git. Not a full-time engineer — explain
non-obvious engineering decisions, don't assume deep tooling fluency.
Learning is a first-class goal of this project, not just shipping.

## Environment

- **OS:** Windows 11 + WSL2 (Ubuntu)
- **Python:** 3.12, managed via **`uv`** (NOT pip/conda/poetry — do not
  suggest switching package managers)
- **Database:** DuckDB at `data/processed/worldcup.duckdb`
- **Data source:** `soccerdata` library → Understat (works for top-5
  European leagues). SoFIFA + Sofascore are Cloudflare-blocked — don't
  retry them.
- **Repo:** `~/worldcup-2026` locally; GitHub
  `indraneelk1997-alt/worldcup-2026`
- **Editor/tools:** VS Code, git. Maintainer runs commands themselves
  unless Cowork is driving.

## Directory conventions

- `src/load/` — loader scripts (CREATE IF NOT EXISTS + INSERT OR IGNORE)
- `src/load/v2_ingest/` — V1.04 ingest module (newer, parametrized)
- `src/tools/` — utilities (e.g. `dump_db_schema.py`)
- `docs/` — design docs and references (markdown)
- `data/processed/` — the DuckDB file

## How we work together (collaboration rules)

These are the hard-won rules. They override default helpfulness.

1. **One small step per response.** Don't generate multiple files or
   chain many actions before checking in. This is a learning project;
   pace matters more than throughput.
2. **Design before code.** Have the design conversation — even for
   mechanical-seeming items — before writing implementation. Capture
   decisions in a `docs/` file when they're non-trivial.
3. **Observe, don't infer.** (The "S14 lesson.") Primary sources —
   dataframe column dumps, transaction dry-runs, live DB queries — beat
   secondary inference from docstrings or catalog queries, every time.
   When you can check, check. Don't guess a column name you could print.
4. **Mirror the real execution context when testing.** (The "S16
   lesson.") A test that passes in a different context than production
   proves nothing. If prod wraps things in one transaction, the test
   must too.
5. **Push back on bad approaches.** Don't agree to something technically
   unsound to be agreeable. Disagree, explain, propose better.
6. **Cite URLs when claiming facts about tools/libraries.** Don't assert
   DuckDB/soccerdata behavior from memory when docs exist.
7. **Keep responses short.** Long responses tax the maintainer and bury
   the signal. Be concise.
8. **Use `🐢` at pause points** where the maintainer should act/decide
   before you continue. Use `✅` when a step is confirmed working.
9. **Don't redo the data layer.** Don't drop tables in load scripts
   unless explicitly told. Append-only is the default posture.
10. **Update `docs/session_state.md` at the end of a working session**
    so the next session resumes cleanly.

## Recurring DuckDB gotchas (verified, not inferred)

- Season strings stored full-form: `'2024-2025'` / `'2025-2026'`.
  Understat internally uses `'2425'` / `'2526'`; `SEASON_MAP` exists in
  older loaders to bridge this.
- **`ADD COLUMN` cannot include a constraint** in the same statement
  ("Adding columns with constraints not yet supported"). Decompose:
  ADD plain column → UPDATE backfill → `ALTER COLUMN ... SET NOT NULL`.
- **`SET NOT NULL` cannot run in the same transaction as the UPDATE that
  backfilled the rows** ("Cannot create index with outstanding
  updates"). The backfill must be committed first. (Confirmed S16;
  fix approach in `docs/session_state.md` until verified + folded here.)
- DuckDB lacks `ADD COLUMN IF NOT EXISTS` — check column existence first
  for idempotency.
- DuckDB `ALTER` doesn't support CHECK constraints — enforce in app code.
- FK column types must match **exactly**.
- `duckdb_constraints()` does NOT reliably report all FKs. Use the
  column-name graph in `docs/db_schema.md` as a backup view.
- `positions` table has a `flank` NOT NULL column — INSERTs must include it.

## Understat / soccerdata notes

- La Liga via Understat works; columns identical to Premier League
  (29 cols: `home_team`, `away_team`, `home_xg`, etc.).
- Understat returns a `league` column natively (e.g. `'ESP-La Liga'`).
- Understat `game_id` space is global across leagues — no collision risk.
- Each top-5 league: 20 teams × 38 matchdays = 380 matches/season.

## External references

- Notion tracker exists but was last maintained around S12 — useful as
  historical reference, not current source of truth. The repo markdown
  files are canonical now.
- `docs/v104_ingest_design.md` — V1.04 ingest architecture decisions.
- `docs/db_schema.md` — auto-generated schema reference (regenerate via
  `src/tools/dump_db_schema.py`).