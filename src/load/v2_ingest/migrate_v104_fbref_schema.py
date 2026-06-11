"""
S22 step 4 — additive schema migration for FBref ingest (Option C).

Implements docs/v104_schema_migration.md against the OBSERVED column
shapes from the S22 probes (not inferred). Additive ONLY:
  ADD COLUMN (plain, nullable) / INSERT / CREATE TABLE / CREATE VIEW.
No drops, no NOT NULL relaxation, no ALTER on FK-referenced tables.

DuckDB rules respected (Claude.md "Recurring DuckDB gotchas"):
  * no ADD COLUMN IF NOT EXISTS -> we check column existence first
  * ADD COLUMN can't carry a constraint -> all adds plain nullable
  * positions.flank is NOT NULL -> new rows include flank='C'
  * FK column types must match exactly -> game_id/player_id INTEGER
  * per-statement autocommit, no outer transaction (S16/S17);
    every step idempotent and independently re-runnable.

Shared dimensions (games/players/positions) take additive changes;
FBref facts land in NEW tables team_match_fbref / player_match_fbref;
Understat fact tables are left untouched. Cross-source via union views.

SAFETY: defaults to --dry-run (prints the plan, no writes). Pass
--apply to actually execute. Run only after the pre-flight gates in
docs/v104_schema_migration.md pass.

    uv run python src/load/v2_ingest/migrate_v104_fbref_schema.py            # dry-run
    uv run python src/load/v2_ingest/migrate_v104_fbref_schema.py --apply    # execute
"""

from __future__ import annotations

import argparse
import sys

import duckdb

DB_PATH = "data/processed/worldcup.duckdb"

# --- new coarse position codes (decision d). GK/granular already exist;
#     AM is aliased to CAM in the loader, so no AM row here. ---
NEW_POSITION_CODES = [
    # (position_code, position_class, flank, position_class_v103)
    ("DF", "DEF", "C", None),
    ("MF", "MID", "C", None),
    ("FW", "FWD", "C", None),
]

# --- additive columns on shared dimensions ---
GAMES_NEW_COLUMNS = [
    ("source", "VARCHAR"),          # decision (a): provenance
    ("source_game_id", "VARCHAR"),  # native FBref hash; Understat -> NULL/str(id) later
    ("stage", "VARCHAR"),           # decision (b): round/knockout label
    ("venue", "VARCHAR"),           # decision (b): stadium name (from read_schedule)
    ("home_goals", "INTEGER"),      # decision (c)
    ("away_goals", "INTEGER"),
    ("home_pens", "INTEGER"),
    ("away_pens", "INTEGER"),
]

PLAYERS_NEW_COLUMNS = [
    ("player_dob", "DATE"),         # decision (e): back-computed from age
]

# --- new FBref fact tables (column lists from observed probe output) ---
DDL_TEAM_MATCH_FBREF = """
CREATE TABLE IF NOT EXISTS team_match_fbref (
    game_id        INTEGER NOT NULL,   -- surrogate; FK -> games.game_id
    team           VARCHAR NOT NULL,
    side           VARCHAR,            -- 'home'/'away' (from team_match 'venue' Home/Away)
    season         VARCHAR NOT NULL,   -- DB form '2024-2025' (mapped from '2425')
    opponent       VARCHAR,
    league         VARCHAR NOT NULL,   -- assigned explicitly post all-comps filter
    goals          INTEGER,            -- GF
    opponent_goals INTEGER,            -- GA
    result         VARCHAR,            -- W/D/L
    possession     DOUBLE,             -- Poss
    attendance     INTEGER,
    captain        VARCHAR,
    formation      VARCHAR,
    opp_formation  VARCHAR,            -- 'Opp Formation'
    referee        VARCHAR,
    PRIMARY KEY (game_id, team),
    FOREIGN KEY (game_id) REFERENCES games (game_id)
)
"""

DDL_PLAYER_MATCH_FBREF = """
CREATE TABLE IF NOT EXISTS player_match_fbref (
    game_id            INTEGER NOT NULL,  -- FK -> games.game_id
    player_id          INTEGER NOT NULL,  -- minted surrogate; FK -> players.player_id
    season             VARCHAR NOT NULL,
    team               VARCHAR NOT NULL,
    league             VARCHAR NOT NULL,
    position           VARCHAR,           -- raw FBref 'pos' (e.g. 'DF,MF')
    effective_position VARCHAR,           -- primary token, policy-resolved
    position_id        INTEGER,           -- -> positions.position_code
    jersey_number      INTEGER,
    nation             VARCHAR,
    minutes            INTEGER,           -- min
    goals              INTEGER,           -- Performance.Gls
    assists            INTEGER,           -- Ast
    pens_made          INTEGER,           -- PK
    pens_att           INTEGER,           -- PKatt
    shots              INTEGER,           -- Sh
    shots_on_target    INTEGER,           -- SoT
    yellow_cards       INTEGER,           -- CrdY
    red_cards          INTEGER,           -- CrdR
    fouls              INTEGER,           -- Fls
    fouled             INTEGER,           -- Fld
    offsides           INTEGER,           -- Off
    crosses            INTEGER,           -- Crs
    tackles_won        INTEGER,           -- TklW
    interceptions      INTEGER,           -- Int
    own_goals          INTEGER,           -- OG
    pens_won           INTEGER,           -- PKwon
    pens_conceded      INTEGER,           -- PKcon
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id)   REFERENCES games (game_id),
    FOREIGN KEY (player_id) REFERENCES players (player_id)
)
"""

# --- cross-source union views over the shared spine ---
DDL_TEAM_MATCH_ALL = """
CREATE OR REPLACE VIEW team_match_all AS
SELECT game_id, team, side, season, opponent, league, goals,
       'understat' AS source
FROM team_match_stats
UNION ALL
SELECT game_id, team, side, season, opponent, league, goals,
       'fbref' AS source
FROM team_match_fbref
"""

DDL_PLAYER_MATCH_ALL = """
CREATE OR REPLACE VIEW player_match_all AS
SELECT game_id, player_id, season, team, league, position,
       minutes, goals, assists, 'understat' AS source
FROM player_match_stats
UNION ALL
SELECT game_id, player_id, season, team, league, position,
       minutes, goals, assists, 'fbref' AS source
FROM player_match_fbref
"""


def column_exists(con, table: str, column: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()
    return row is not None


def table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
        [table],
    ).fetchone()
    return row is not None


def log(msg: str) -> None:
    print(f"  {msg}")


def run(con, sql: str, apply: bool) -> None:
    if apply:
        con.execute(sql)
        log(f"APPLIED: {sql.strip().splitlines()[0][:70]} ...")
    else:
        log(f"WOULD RUN: {sql.strip().splitlines()[0][:70]} ...")


def migrate(apply: bool) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    print("=" * 70)
    print(f"  V1.04 FBref schema migration — {mode}")
    print(f"  DB: {DB_PATH}")
    print("=" * 70)

    con = duckdb.connect(DB_PATH, read_only=not apply)
    try:
        # Step 1 + 2: additive columns on games / players
        print("\n-- Step 1/2: shared-dimension columns --")
        for table, cols in (("games", GAMES_NEW_COLUMNS),
                            ("players", PLAYERS_NEW_COLUMNS)):
            for name, dtype in cols:
                if column_exists(con, table, name):
                    log(f"skip {table}.{name} (exists)")
                else:
                    run(con, f"ALTER TABLE {table} ADD COLUMN {name} {dtype}",
                        apply)

        # backfill source = 'understat' for pre-existing rows
        if column_exists(con, "games", "source"):
            if apply:
                con.execute(
                    "UPDATE games SET source = 'understat' WHERE source IS NULL"
                )
                log("APPLIED: backfill games.source = 'understat'")
            else:
                n = con.execute(
                    "SELECT COUNT(*) FROM games WHERE source IS NULL"
                ).fetchone()[0]
                log(f"WOULD backfill games.source='understat' on {n} rows")

        # Step 3: new coarse position codes (decision d)
        print("\n-- Step 3: coarse position codes DF/MF/FW (decision d) --")
        existing = {r[0] for r in con.execute(
            "SELECT position_code FROM positions"
        ).fetchall()}
        for code, pclass, flank, v103 in NEW_POSITION_CODES:
            if code in existing:
                log(f"skip positions.{code} (exists)")
            elif apply:
                con.execute(
                    "INSERT INTO positions "
                    "(position_code, position_class, flank, position_class_v103) "
                    "VALUES (?, ?, ?, ?)",
                    [code, pclass, flank, v103],
                )
                log(f"APPLIED: INSERT positions {code} ({pclass}, flank={flank})")
            else:
                log(f"WOULD INSERT positions {code} ({pclass}, flank={flank})")

        # Step 4: new FBref fact tables
        print("\n-- Step 4: FBref fact tables (Option C) --")
        for name, ddl in (("team_match_fbref", DDL_TEAM_MATCH_FBREF),
                          ("player_match_fbref", DDL_PLAYER_MATCH_FBREF)):
            if table_exists(con, name):
                log(f"skip {name} (exists)")
            else:
                run(con, ddl, apply)

        # Step 5: union views
        print("\n-- Step 5: cross-source union views --")
        for name, ddl in (("team_match_all", DDL_TEAM_MATCH_ALL),
                          ("player_match_all", DDL_PLAYER_MATCH_ALL)):
            run(con, ddl, apply)

        print("\n" + "=" * 70)
        if apply:
            print("  DONE — applied. Re-run to confirm idempotency (all 'skip').")
            print("  Next: regenerate docs/db_schema.md via dump_db_schema.py.")
        else:
            print("  DRY-RUN complete — no writes. Re-run with --apply to execute.")
        print("=" * 70)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="execute writes (default: dry-run, read-only)")
    args = ap.parse_args()
    sys.exit(migrate(apply=args.apply))
