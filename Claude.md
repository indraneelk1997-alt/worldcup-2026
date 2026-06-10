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
11. **(S20–S22 trial.)** For the next few sessions, do not push back on
    tasks for being "too long" or "too big a detour." Surface subtasks
    and scope-expansion notes, then ask whether to split across
    sessions or pass in one — let Indraneel make the call. Sunset this
    rule after S22 unless renewed.

## Recurring DuckDB gotchas (verified, not inferred)

- Season strings stored full-form: `'2024-2025'` / `'2025-2026'`.
  Understat internally uses `'2425'` / `'2526'`; `SEASON_MAP` exists in
  older loaders to bridge this.
- **`ADD COLUMN` cannot include a constraint** in the same statement
  ("Adding columns with constraints not yet supported"). Decompose:
  ADD plain column → UPDATE backfill → `ALTER COLUMN ... SET NOT NULL`.
- **`SET NOT NULL` cannot run in the same transaction as the UPDATE that
  backfilled the rows** ("Cannot create index with outstanding
  updates"). The backfill must be committed first. (S16, verified S17
  in-memory.) Practical consequence: don't wrap a multi-step migration
  in one outer transaction. Per-statement autocommit, idempotent re-run.
- **`ALTER COLUMN ... SET NOT NULL` is blocked on FK-referenced tables.**
  Any ALTER on a table other tables hold a declared FK into raises
  `Dependency Error: Cannot alter entry 'X' because there are entries
  that depend on it` (S17, [duckdb/duckdb#17348](https://github.com/duckdb/duckdb/issues/17348)).
  DuckDB has no `DROP/ADD CONSTRAINT` ([#4204](https://github.com/duckdb/duckdb/discussions/4204))
  and no `PRAGMA foreign_keys = OFF` ([#4205](https://github.com/duckdb/duckdb/discussions/4205)),
  so the Postgres-style "drop FKs, alter, re-add" workaround is closed.
  Enforce non-nullity in app code for FK-referenced tables. Detect at
  runtime via `duckdb_constraints() WHERE constraint_type='FOREIGN KEY'
  AND referenced_table = ?` (caveat: this view under-reports — see below).
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
- Understat returns a `league` value as a **MultiIndex level**, NOT a
  column (verified S18). All three Understat endpoints
  (`read_schedule`, `read_player_match_stats`, `read_team_match_stats`)
  use the same MultiIndex shape with `league` at level 0. Strings are
  `'ENG-Premier League'`, `'ESP-La Liga'`, etc. — soccerdata's
  canonical league codes, used for both input (`leagues=[...]`) and
  output. No translation needed.
- `season` MultiIndex value is `'2425'` / `'2526'`; our DB uses
  `'2024-2025'` / `'2025-2026'`. V1.04's `ingest_understat.py` has
  a `SEASON_DB_TO_SD` map; V1.03 had `SEASON_MAP`. Both still in use.
- Understat `game_id` space is global across leagues — no collision risk.
- Understat data can occasionally contain **whole-game duplicate rows**
  in `read_player_match_stats` — every player from a single match
  appears twice, byte-for-byte identical. PK on `(game_id, player_id)`
  + `INSERT OR IGNORE` handles it cleanly with no information loss.
  Confirmed example (S18): La Liga 2025-26 `game_id=29482` (Villarreal
  vs Real Oviedo) — 32 player rows duplicated.
- Each top-5 league: 20 teams × 38 matchdays = 380 matches/season.
- `players` is a FK parent of `player_match_stats` — any loader that
  writes to `player_match_stats` must INSERT OR IGNORE new
  `(player_id, player_name)` pairs into `players` first. V1.04's
  `ingest_understat.py` does this inside Section B; V1.03 mirrors in
  `backfill_player_match.py` step 10a and `load_md38_actuals.py`.
- **FRA-Ligue 1 2025-26 source gap (S19, banked S20):** schedule has
  306 games but `read_team_match_stats` returns only 305 — one game
  missing from Understat's team-match endpoint (postponed/in-progress).
  Captured by `validate_v104_ingest.py` section 5; the join still
  passes its invariant on the 305 with data. Benign source gap, not
  our bug.

## soccerdata extension (S20)

- **Default `available_leagues()` is a curated subset, not the source's
  full capability.** Off-the-shelf FBref/WhoScored only expose Euro +
  WC + Women's WC for internationals; ESPN only Big-5 domestic.
- **Custom league overlay:** soccerdata reads
  `~/soccerdata/config/league_dict.json` at import and merges it on top
  of `_config.py:LEAGUE_DICT`. Custom entries unlock arbitrary FBref
  competitions. Entry shape mirrors the default — canonical key (e.g.,
  `"UEFA-Champions League"`) → per-scraper internal name + optional
  `season_start` / `season_end` (or `"season_code": "single-year"` for
  tournaments).
- **FBref lookup is exact-match on `competition_name`.** Wrong string
  → silent empty df → `pd.concat([])` ValueError (in `read_seasons`),
  no friendly "league not found" error. Always verify the FBref string
  against the on-page `competition_name` column at fbref.com/en/comps/.
- **Em-dash gotcha in WCQ names:** FBref's WC qualifying competition
  names use the em-dash character `—` (U+2014), not a hyphen — e.g.,
  `"FIFA World Cup Qualification — UEFA"`. Wrong byte → empty df.
- **FBref rate limit:** 7s between requests (`fbref.py:97`). One season
  of per-match player stats ≈ 22 min wall for a CL-sized competition.
  Cached locally after first fetch.

## External references

- Notion tracker exists but was last maintained around S12 — useful as
  historical reference, not current source of truth. The repo markdown
  files are canonical now.
- `docs/v104_ingest_design.md` — V1.04 ingest architecture decisions.
- `docs/db_schema.md` — auto-generated schema reference (regenerate via
  `src/tools/dump_db_schema.py`).