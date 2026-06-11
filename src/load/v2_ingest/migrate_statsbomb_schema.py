"""
S25 — additive schema migration for the StatsBomb Open sidecar.

Implements docs/statsbomb_ingest_design.md (D1-D3b) against the OBSERVED
shapes from the S25 Euro-2024 pilot (match_id 3930158), not inferred.

Self-contained sidecar on StatsBomb's own ID space: four NEW tables, ZERO
links into games/players. Nothing existing is touched -> no DuckDB FK-block
exposure (Claude.md gotchas). Cross-walk to our players/squad is a SEPARATE
resolver pass, later — not here.

Additive ONLY: CREATE TABLE IF NOT EXISTS. No drops, no ALTERs.

Design divergences from migrate_v104_fbref_schema.py (intentional):
  * NO declared FKs among the sidecar tables. event_uuid/match_id links are
    app-enforced plain columns (mirrors wc2026_squad.our_player_id), keeping
    these still-evolving tables free of the FK-ALTER lock-in, and load order
    flexible. An orphan-check belongs in the validator, not a constraint.
  * The DRY-RUN actually compiles every DDL in an in-memory DuckDB (rule 4 —
    mirror real exec context), so a bad type / reserved word fails loud
    BEFORE the real apply. 'index' is renamed -> 'event_index' (reserved).
  * 'raw' is the native JSON type (un-promoted fields recoverable via
    json_extract); the in-memory compile confirms the bundled json extension
    accepts it before apply.

    uv run python src/load/v2_ingest/migrate_statsbomb_schema.py            # dry-run (+ in-mem validate)
    uv run python src/load/v2_ingest/migrate_statsbomb_schema.py --apply    # execute
"""

from __future__ import annotations

import argparse
import sys

import duckdb

DB_PATH = "data/processed/worldcup.duckdb"

# --- match dimension (one row per StatsBomb match) ---
DDL_STATSBOMB_MATCH = """
CREATE TABLE IF NOT EXISTS statsbomb_match (
    match_id             INTEGER PRIMARY KEY,
    competition_id       INTEGER NOT NULL,
    season_id            INTEGER NOT NULL,   -- (competition_id, season_id) = the real key
    match_date           DATE,
    kick_off             VARCHAR,
    match_week           INTEGER,
    competition_stage_id INTEGER,
    competition_stage    VARCHAR,
    home_team_id         INTEGER,
    home_team            VARCHAR,
    away_team_id         INTEGER,
    away_team            VARCHAR,
    home_score           INTEGER,
    away_score           INTEGER,
    stadium_id           INTEGER,
    stadium              VARCHAR,
    referee_id           INTEGER,
    referee              VARCHAR,
    source               VARCHAR DEFAULT 'statsbomb_open',
    ingested_at          TIMESTAMP DEFAULT now()
)
"""

# --- event fact (curated typed cols + raw JSON; one row per event) ---
DDL_STATSBOMB_EVENT = """
CREATE TABLE IF NOT EXISTS statsbomb_event (
    id                  VARCHAR PRIMARY KEY,   -- event uuid
    match_id            INTEGER NOT NULL,      -- app-enforced -> statsbomb_match.match_id
    competition_id      INTEGER,               -- denormalized for tournament filtering
    season_id           INTEGER,
    event_index         INTEGER,               -- StatsBomb 'index' (reserved word -> renamed)
    period              INTEGER,
    timestamp           VARCHAR,               -- clock string '00:00:00.000'
    minute              INTEGER,
    second              INTEGER,
    type                VARCHAR,
    possession          INTEGER,
    possession_team     VARCHAR,
    possession_team_id  INTEGER,
    team_id             INTEGER,
    team                VARCHAR,
    player_id           INTEGER,
    player              VARCHAR,
    position            VARCHAR,
    play_pattern        VARCHAR,
    x                   DOUBLE,                -- location[0]
    y                   DOUBLE,                -- location[1]
    end_x               DOUBLE,                -- coalesced *_end_location[0]
    end_y               DOUBLE,                -- coalesced *_end_location[1]
    duration            DOUBLE,
    outcome             VARCHAR,               -- coalesced *_outcome
    body_part           VARCHAR,               -- coalesced *_body_part
    under_pressure      BOOLEAN,
    pass_recipient_id   INTEGER,
    shot_xg             DOUBLE,                -- shot_statsbomb_xg
    raw                 JSON                   -- full nested event (lossless)
)
"""

# --- 360 freeze-frame fact (event x actor; anonymized occupancy) ---
DDL_STATSBOMB_FRAME = """
CREATE TABLE IF NOT EXISTS statsbomb_frame (
    event_uuid  VARCHAR NOT NULL,   -- app-enforced -> statsbomb_event.id
    match_id    INTEGER NOT NULL,
    frame_idx   INTEGER NOT NULL,   -- position within the freeze_frame array
    x           DOUBLE,
    y           DOUBLE,
    teammate    BOOLEAN,
    actor       BOOLEAN,
    keeper      BOOLEAN,
    PRIMARY KEY (event_uuid, frame_idx)
)
"""

# --- per-event 360 metadata (camera coverage) ---
DDL_STATSBOMB_FRAME_META = """
CREATE TABLE IF NOT EXISTS statsbomb_frame_meta (
    event_uuid    VARCHAR PRIMARY KEY,   -- app-enforced -> statsbomb_event.id
    match_id      INTEGER NOT NULL,
    visible_area  JSON                   -- camera polygon [x,y,...]
)
"""

TABLES = [
    ("statsbomb_match", DDL_STATSBOMB_MATCH),
    ("statsbomb_event", DDL_STATSBOMB_EVENT),
    ("statsbomb_frame", DDL_STATSBOMB_FRAME),
    ("statsbomb_frame_meta", DDL_STATSBOMB_FRAME_META),
]


def table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
        [table],
    ).fetchone()
    return row is not None


def log(msg: str) -> None:
    print(f"  {msg}")


def validate_in_memory() -> tuple[bool, str | None]:
    """Compile every DDL on a throwaway in-memory DB (rule 4). Also re-run
    each CREATE twice to prove IF NOT EXISTS idempotency."""
    mem = duckdb.connect(":memory:")
    try:
        for _name, ddl in TABLES:
            mem.execute(ddl)
            mem.execute(ddl)  # second time must be a no-op, not an error
        return True, None
    except Exception as e:  # noqa: BLE001 - surface anything
        return False, repr(e)
    finally:
        mem.close()


def migrate(apply: bool) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    print("=" * 70)
    print(f"  StatsBomb sidecar schema migration — {mode}")
    print(f"  DB: {DB_PATH}")
    print("=" * 70)

    # In-memory compile + idempotency check runs in BOTH modes (cheap, safe).
    print("\n-- DDL validation (in-memory compile + idempotency) --")
    ok, err = validate_in_memory()
    if not ok:
        print(f"  FAILED to compile DDL in-memory: {err}")
        print("  Aborting — fix the DDL before touching the real DB.")
        return 1
    log("all 4 CREATEs compile + are idempotent in-memory  OK")

    con = duckdb.connect(DB_PATH, read_only=not apply)
    try:
        print("\n-- sidecar tables on the real DB --")
        for name, ddl in TABLES:
            if table_exists(con, name):
                log(f"skip {name} (exists)")
            elif apply:
                con.execute(ddl)
                log(f"APPLIED: CREATE {name}")
            else:
                log(f"WOULD CREATE {name}")

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
