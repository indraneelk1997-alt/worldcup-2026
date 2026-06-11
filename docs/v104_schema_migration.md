# V1.04 schema migration — FBref ingest (Option C)

**Status**: design locked S22 step 3. **No code executed yet.** This
doc is the migration plan + DDL sketch. Migration code lands in a
separate session (S22 step 4+) only after the pre-flight gates below
pass. Decisions captured in
[`docs/v104_ingest_competitions.md`](v104_ingest_competitions.md)
("Schema deltas — RESOLVED S22 step 3"); this doc is canonical for the
*how*.

**Governing architecture**: Option C — source-separated FBref fact
tables. Understat fact tables untouched; three shared dimensions take
additive changes only; FBref per-match data lands in new tables;
cross-source reads via union views.

## Why this migration is low-risk

Every step is **additive**: `ADD COLUMN` (plain, nullable), `INSERT`,
`CREATE TABLE`, `CREATE VIEW`. Nothing is dropped, no table is
recreated, no NOT NULL is relaxed, no FK-referenced table is `ALTER`ed
in a blocked way. This is a deliberate consequence of decision (a)
(surrogate `game_id`, not VARCHAR recreate) and (h) (source-separated
tables, not in-place union). It sidesteps every documented DuckDB
migration gotcha (Claude.md "Recurring DuckDB gotchas"):

- No `ALTER COLUMN ... SET NOT NULL` on FK-referenced tables (the S17
  block) — we never set NOT NULL on `games`/`players`.
- No `DROP/ADD CONSTRAINT`, no `PRAGMA foreign_keys = OFF` needed.
- No multi-step backfill-then-constrain dance, so no outer-transaction
  hazard (S16). New columns stay nullable.

## DuckDB mechanics to respect (verified facts, Claude.md)

- **No `ADD COLUMN IF NOT EXISTS`** — each step must check column
  existence first for idempotency (query `duckdb_columns()` /
  `information_schema.columns`, add only if absent).
- **`ADD COLUMN` cannot carry a constraint** in the same statement —
  all adds are plain nullable columns; that's all we need here.
- **Per-statement autocommit; do NOT wrap in one outer transaction.**
  Each step idempotent and independently re-runnable.
- **`positions.flank` is NOT NULL** — the 3 new rows must include it
  (`'C'`).
- **FK column types must match exactly** — `team_match_fbref.game_id`
  and `player_match_fbref.game_id` are `INTEGER` to match
  `games.game_id`; `player_match_fbref.player_id` is `INTEGER` to match
  `players.player_id`.

## Pre-flight gates (HARD — run before any migration statement)

These are the "observe, don't infer" checks owed from S22. None were
runnable in the S22 design session (no shell). Gate the migration on
them:

1. **Git + DB state.** `git log --oneline -5` (expect HEAD `c9b4ff0`,
   5 ahead of `origin/main`), `git status --short` (expect clean), and
   re-run `validate_v104_ingest.py` (expect 9/10 Understat, no FBref
   rows yet). Confirm nothing touched the soccerdata package, loader,
   DB, or `~/soccerdata/config/league_dict.json` overlay since S21.
2. **Live FK cross-check.** `duckdb_constraints() WHERE
   constraint_type='FOREIGN KEY' AND referenced_table='games'` — and
   cross-check against the column-name graph in `db_schema.md` (the
   view under-reports, Claude.md). We must know the *complete* set of
   tables FK'ing into `games` before trusting "additive only." Option C
   doesn't recreate `games`, so this is a sanity check, not a
   blocker — but verify anyway.
3. **`team_match` `game_id` exposure.** Inspect the cached 1,121-row
   S21 `team_match` probe df: is `game_id` a column, or must we parse
   the 8-char hash from `match_report`? Drives the decision-(g) filter
   implementation.
4. **FBref string shapes.** From the S21 cache (`~/soccerdata/data/FBref/`,
   instant hits, no rate-limit): (a) a real UCL knockout score string
   with shootout/aet, to pin the decision-(c) regex; (b) the exact
   MultiIndex leaf names + which columns arrive blank-topped, to freeze
   `FBREF_COL_MAP` (decision f).

## Migration steps (additive, idempotent, autocommit each)

### Step 1 — `games` shared-dimension columns

```sql
-- decision (a): surrogate-id provenance
ALTER TABLE games ADD COLUMN source         VARCHAR;   -- if absent
ALTER TABLE games ADD COLUMN source_game_id VARCHAR;   -- if absent
UPDATE games SET source = 'understat' WHERE source IS NULL;
-- (source_game_id left NULL for existing Understat rows; optional
--  later backfill = str(game_id). Natural-key uniqueness
--  (source, source_game_id) enforced in app code, not DB.)

-- decision (b): stage + venue
ALTER TABLE games ADD COLUMN stage VARCHAR;   -- NOT named "round" (ROUND() clash)
ALTER TABLE games ADD COLUMN venue VARCHAR;

-- decision (c): structured score
ALTER TABLE games ADD COLUMN home_goals INTEGER;
ALTER TABLE games ADD COLUMN away_goals INTEGER;
ALTER TABLE games ADD COLUMN home_pens  INTEGER;
ALTER TABLE games ADD COLUMN away_pens  INTEGER;
```

All nullable. `games` is FK-referenced → NOT NULL impossible anyway;
presence-for-FBref-rows enforced app-side in `ingest_fbref.py`.

### Step 2 — `players` DOB (decision e)

```sql
ALTER TABLE players ADD COLUMN player_dob DATE;   -- if absent, nullable
```

Understat rows stay NULL. FBref loader back-computes from age text via
`relativedelta`. Validator asserts multi-match DOB agreement per player.

### Step 3 — `positions` coarse FBref codes (decision d)

```sql
-- GK already exists (class GK, flank C) → reused, not re-inserted.
INSERT INTO positions (position_code, position_class, flank, position_class_v103)
VALUES ('DF', 'DEF', 'C', NULL),
       ('MF', 'MID', 'C', NULL),
       ('FW', 'FWD', 'C', NULL)
ON CONFLICT DO NOTHING;   -- or app-side existence check; flank NOT NULL satisfied
```

Verify `position_class` literals match the existing vocabulary
(`DEF`/`MID`/`FWD`/`GK`) against live data before insert.

### Step 4 — new FBref fact tables (decision h, Option C)

Column lists are a **draft** — finalize against the observed FBref
column dump (pre-flight gate 4) before creating. No xG columns (none
served). `CREATE TABLE IF NOT EXISTS`.

```sql
CREATE TABLE IF NOT EXISTS team_match_fbref (
    game_id        INTEGER NOT NULL,   -- FK -> games.game_id (surrogate for FBref)
    team           VARCHAR NOT NULL,
    side           VARCHAR NOT NULL,   -- home/away
    season         VARCHAR NOT NULL,
    opponent       VARCHAR NOT NULL,
    league         VARCHAR NOT NULL,   -- assigned explicitly post-filter
    goals          INTEGER,
    opponent_goals INTEGER,
    -- counting stats FBref still serves (cards, fouls, ...) TBD from dump
    -- bonus columns (decision h):
    formation      VARCHAR,
    opp_formation  VARCHAR,
    captain        VARCHAR,
    PRIMARY KEY (game_id, team),
    FOREIGN KEY (game_id) REFERENCES games (game_id)
);

CREATE TABLE IF NOT EXISTS player_match_fbref (
    game_id            INTEGER NOT NULL,   -- FK -> games.game_id
    player_id          INTEGER NOT NULL,   -- FK -> players.player_id (FBref-native)
    season             VARCHAR NOT NULL,
    team               VARCHAR NOT NULL,
    league             VARCHAR NOT NULL,
    position           VARCHAR,            -- raw FBref 'DF,MF'
    effective_position VARCHAR,            -- primary token, decision (d)
    position_id        INTEGER,            -- -> positions (coarse code)
    minutes            INTEGER,
    goals              INTEGER,
    -- other Performance counting stats TBD from dump
    jersey_number      INTEGER,            -- bonus (decision h)
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id)   REFERENCES games (game_id),
    FOREIGN KEY (player_id) REFERENCES players (player_id)
);
```

`players` dimension maintenance: before inserting into
`player_match_fbref`, `INSERT OR IGNORE` new `(player_id, player_name)`
pairs into `players` (same posture as `ingest_understat.py` Section B).

### Step 5 — cross-source union views

Shared spine only; each source contributes its dense columns, with
source-specific columns surfaced where present.

```sql
CREATE OR REPLACE VIEW team_match_all AS
SELECT game_id, team, side, season, opponent, league, goals,
       'understat' AS source
FROM team_match_stats
UNION ALL
SELECT game_id, team, side, season, opponent, league, goals,
       'fbref' AS source
FROM team_match_fbref;
-- (player_match_all analogous; column set finalized after gate 4)
```

Downstream model code that currently reads `team_match_stats` directly
keeps working unchanged; cross-source consumers read the view.

## Idempotency & re-run posture

- Each `ALTER`/`INSERT`/`CREATE` guarded by an existence check (no
  DuckDB `IF NOT EXISTS` for columns).
- Re-running the whole migration is a no-op once applied.
- No outer transaction; if a step fails, fix and re-run from the top —
  earlier steps no-op.

## After migration (separate later steps)

- Regenerate `docs/db_schema.md` (`src/tools/dump_db_schema.py`).
- Build `ingest_fbref.py` (S22 step 6) carrying all parsing logic:
  surrogate-id assignment (a), `read_schedule` membership filter (g),
  score parse (c), MultiIndex flatten + fail-loud `FBREF_COL_MAP` (f),
  source-aware `_position_policy` primary-token (d), age→DOB (e).
- Extend `validate_v104_ingest.py`: `stage` label set check, score vs
  `team_match_fbref` goals cross-check, multi-match DOB agreement,
  `team_match == 2×games` on the FBref tables.

## References

- Decisions + rationale:
  [`docs/v104_ingest_competitions.md`](v104_ingest_competitions.md).
- DuckDB migration gotchas (verified): `Claude.md` → "Recurring DuckDB
  gotchas", citing
  [duckdb/duckdb#17348](https://github.com/duckdb/duckdb/issues/17348)
  (ALTER on FK-referenced tables),
  [#4204](https://github.com/duckdb/duckdb/discussions/4204)
  (no DROP/ADD CONSTRAINT),
  [#4205](https://github.com/duckdb/duckdb/discussions/4205)
  (no `foreign_keys = OFF`).
- soccerdata FBref behaviour: `Claude.md` → "soccerdata FBref
  behaviour"; source at
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/fbref.py`.
- FBref/Opta termination (no xG): Jan 20, 2026 — see
  `docs/v104_ingest_competitions.md` "Critical context".
