"""
V1.02 modeling — STEP 5b: add player_positions table.

WHAT THIS DOES
    Creates a new `player_positions` table that holds ALL position classes
    a player is eligible to play for a given (season, team), not just the
    primary one. This unblocks multi-position lineup selection in S8 — a
    player listed by Understat as 'F M' becomes eligible for BOTH forward
    and midfielder slots.

RELATIONSHIP TO EXISTING `position_class` COLUMN
    player_season_stats.position_class is kept as-is. It holds the PRIMARY
    class (Understat's first token, decoded). It will always equal the
    player_positions row with priority=1 for that (player, season, team).
    The single column is a denormalized convenience; the table is the
    source of truth for "which classes is this player eligible for?".

WHY KEEP BOTH (S8 DECISION)
    1. Existing code (compute_shrinkage.py, select_best_xi.py from earlier
       in S8) already reads position_class — no refactor needed.
    2. The column is useful in its own right: "this player's primary role".
    3. Duplication is harmless and queryable (position_class equals the
       priority=1 row).

SCHEMA NOTES
    - PK (player_id, season, team, position_class): a player can have
      multiple rows for one (season, team), one per eligible class.
    - priority is the order Understat listed the codes: 1 = first token,
      2 = second non-S token, etc. Range 1-4 (handles up to 'D F M S').
    - CHECK on position_class enforces the GK/DEF/MID/FWD vocabulary.

IDEMPOTENCY
    CREATE TABLE IF NOT EXISTS. Re-running the backfill script will
    overwrite rows for current data.

HOW TO RUN
    From the repo root:
        uv run python src/model/player_positions_schema.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if "player_positions" in existing:
            print("player_positions table already exists.")
            print("Nothing to do. (Re-run is safe.)")
            return

        print("Creating player_positions table...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("""
                CREATE TABLE player_positions (
                    player_id      INTEGER NOT NULL REFERENCES players(player_id),
                    season         VARCHAR NOT NULL,
                    team           VARCHAR NOT NULL,
                    position_class VARCHAR NOT NULL CHECK (position_class IN ('GK','DEF','MID','FWD')),
                    priority       INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 4),
                    PRIMARY KEY (player_id, season, team, position_class)
                )
            """)
            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during CREATE, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        print("\nplayer_positions columns:")
        rows = con.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'player_positions'
            ORDER BY ordinal_position
            """
        ).fetchall()
        for col_name, dtype, nullable in rows:
            print(f"  {col_name:<18} {dtype:<10} nullable={nullable}")
    finally:
        con.close()


if __name__ == "__main__":
    main()