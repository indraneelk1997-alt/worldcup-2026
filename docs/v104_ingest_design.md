# V1.04 ingest architecture design

**Status**: design captured, implementation pending
**Designed in**: S15 (2026-05-29)
**Carries forward to**: S16+
**Supersedes**: nothing yet (incremental migration; V1.03 loaders remain)

## Problem statement

The project's data trajectory is: more leagues, more competitions, more
matchdays, indefinitely, with appended matchdays as they happen. The
current ingest architecture works for "PL, two seasons,
refresh-on-demand" and does not scale.

Concrete failures of the current (V1.03) architecture:

1. **Wipe-and-reload is destructive.** Scripts delete their season's
   data then re-insert. Worked when the FK graph was simple. Broke in
   S14 (the `team_match_predictions_b12.game_id` undeclared FK).
2. **FK cascades worsen as the schema grows.** Each new child table
   either gets added to every relevant loader's wipe list, or loaders
   fail. We will hit this again.
3. **No incremental update.** Adding MD38 means "rebuild MD1–37 plus
   MD38." Doesn't scale to 5 leagues × 38 matchdays × multiple
   seasons.
4. **Pre-registration fragility.** Computed downstream state
   (`team_season_strength_v103`, `league_averages_v103`, ...) was
   silently being put at risk by raw-data reloads. S13/S14 navigated
   this by hand; the architecture should make staleness visible.

## Design decisions

### 1. Idempotency: `INSERT OR IGNORE`, no content-hash detection

Historical data from a single source is effectively static. The "what
if Understat re-processes?" scenario is hypothetical, not observed in
~2 weeks of project use. Building content-hash defensive
infrastructure adds complexity to solve a problem we have not
encountered.

**Loaders use `INSERT OR IGNORE` everywhere.** New rows go in;
existing rows are untouched.

**Carve-out for World Cup matchdays**: day-of-event re-processing
might matter. Add a `--force` flag to the loader if and when WC starts.
Defer until needed. Not architectural; just a parameter.

### 2. Append-only, no historical re-fetch

Once a season is loaded, it is loaded. New matchday → new append.

The loaders do not compare existing data to source data. They do not
re-fetch historical data unless explicitly forced. They fetch the new
chunk, `INSERT OR IGNORE` it, and stop.

This simplifies the loader significantly: no diff-and-merge logic, no
"what's already there?" detection, no overwrite semantics.

### 3. One file per source, sectioned by table

V1.03 has one file per *table* (`backfill_player_match.py`,
`team_match_load.py`, ...). This split causes the same source to be
fetched twice across separate scripts and forces FK ordering decisions
to be re-derived per file.

V1.04 has **one file per source**, with explicit per-table sections
inside. E.g. `src/load/v2_ingest/ingest_understat.py` contains
clearly-marked sections for `games`, `player_match_stats`,
`team_match_stats` — all using one cached Understat fetch.

Sections are bordered by visible comments. Each section's column
mapping and INSERT statement is independently locatable. The shared
fetch logic lives at the top.

### 4. Explicit derived-state dependency tracking

The "what is fresh and what is stale?" question is currently answered
ad hoc (humans remember, or notice when something breaks). V1.04 makes
this auditable.

**New table** `derived_state_freshness`:

| column | type | purpose |
|---|---|---|
| `derived_table` | VARCHAR | e.g. `team_season_strength_v103` |
| `upstream_tables` | VARCHAR[] | e.g. `['team_match_stats']` |
| `upstream_max_row_count` | INTEGER | upstream row count at last refresh |
| `upstream_max_timestamp` | TIMESTAMP | upstream max timestamp at last refresh, if applicable |
| `last_refreshed_at` | TIMESTAMP | when this derived table was last recomputed |
| `status` | VARCHAR | `'fresh'`, `'stale_but_intentional'`, `'stale_unknown'` |
| `notes` | VARCHAR | free-form justification when status is `'stale_but_intentional'` |

PK: `derived_table` (single row per derived table).

**Behaviour**:

- Loader scripts that append to a raw table do NOT auto-refresh
  derived state. They update `derived_state_freshness` to mark
  affected derived tables as `'stale_unknown'` if upstream row count
  has changed.
- Refresh decisions are **manual**. User explicitly runs the
  derived-state recompute script and chooses when.
- The pre-registration case (S13: predictions made against pre-MD38
  strengths) is handled by setting `status = 'stale_but_intentional'`
  with a `notes` entry. The "stale" state is preserved, the rationale
  is recorded, and future readers can see both.

**New tool** `src/tools/check_freshness.py`:

- Queries `derived_state_freshness`
- Compares current upstream row counts to recorded values
- Reports drift
- Returns non-zero if any table is `'stale_unknown'` (suitable for
  pre-commit hooks if we ever want them)

### 5. Migration: incremental, with version tagging

V1.03 loaders stay in place. V1.04 loaders go in a new directory.
Each architecture is identifiable by location.

**Directory structure**:

- `src/load/` — V1.03 (V1) scripts. Untouched. Add header line:
  `INGEST ARCHITECTURE: v1 (wipe-and-reload, table-centric) — DEPRECATED for new data, kept for reference`
- `src/load/v2_ingest/` — V1.04 (V2) scripts. New work goes here.
  Each file has header line:
  `INGEST ARCHITECTURE: v2 (append-only, source-centric)`

**Migration rules**:

- New tables added going forward use V2 scripts only.
- Old tables only migrate to V2 when there is a concrete reason (a
  V1 script breaks, or we hit pain).
- The `docs/ingest_architecture.md` reference doc records which
  tables are loaded by which architecture.

**Why not big-bang**: solo learning project; risk-aversion favors
keeping known-working pieces operational while new pieces prove
themselves. Living with two patterns is a controlled cost; breaking
working ingest is not.

## Concrete first-build scope

Five deliverables for V1.04 ingest, sized for ~3-4 focused sessions:

1. **Create the new directory**: `src/load/v2_ingest/`
2. **First V2 loader**: `ingest_understat.py` — appends to `games`,
   `player_match_stats`, `team_match_stats`. Replaces the future
   "append a new matchday" workflow currently served by
   `backfill_player_match.py` + `team_match_load.py` +
   `load_md38_actuals.py`.
3. **New table**: `derived_state_freshness`, plus a schema-creation
   script `src/load/v2_ingest/create_freshness_table.py`.
4. **Freshness check tool**: `src/tools/check_freshness.py`.
5. **Architecture doc**: `docs/ingest_architecture.md` — maps tables to
   architectures.

## Out of scope for V1.04 ingest

Deliberately not building:

- Content-hash idempotency (deferred indefinitely; revisit if Understat
  ever silently re-processes data)
- Automated derived-state refresh (manual is the right default; the
  pre-registration case forced this conclusion)
- V1 → V2 retrofitting of existing loaders (only when a V1 loader
  concretely breaks)
- Source-centric design for non-Understat sources (we only use
  Understat in practice; SoFIFA + Sofascore remain Cloudflare-blocked)
- Migration tooling. Each migration is a one-time effort; no tooling
  pays for itself.

## Open questions for S16 implementation start

1. What happens when V2 loaders need to write to a table that V1
   loaders also know how to populate? (E.g. if `ingest_understat.py`
   appends to `games`, but the V1 `backfill_player_match.py` also
   populates `games` when re-run.) Answer: V1 loaders for those
   tables stop being run. The deprecation header makes this explicit.
2. Does the freshness table need a version column for the derived
   table itself? (E.g. distinguish `team_season_strength_v103` from a
   future `team_season_strength_v104`.) Probably yes — add to schema
   when designing.
3. How do we test V2 loaders without polluting the main DB? A scratch
   DB at `data/processed/worldcup_v2_scratch.duckdb`? Worth deciding
   before building.

## References

- S14 retro: `analysis/investigations/md38_b12_b2_evaluation.md` (the
  evaluation work that surfaced the loader bug)
- S14 carry-forward in prior session pickup: cited the loader
  architecture problem as the highest-priority V1.04 item
- DuckDB FK introspection limitation: documented in
  `src/tools/dump_db_schema.py` (S15 piece 1) and visible in
  `docs/db_schema.md`'s column-name graph
- Pre-registration tags from S13: `md38-b12-prereg`, `md38-b2-prereg`
  (relevant context for derived-state-staleness intentionality)