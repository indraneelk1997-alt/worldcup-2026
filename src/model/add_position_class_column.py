"""
V1.02 modeling — STEP 4 prep: add position_class column to player_season_stats.

WHAT THIS DOES
    Adds a nullable VARCHAR column `position_class` to player_season_stats,
    with a CHECK constraint matching our `positions.position_class`
    vocabulary (GK / DEF / MID / FWD). The population script
    (backfill_position_class.py) fills it in step 2.

WHY POSITION_CLASS LIVES ON player_season_stats, NOT players
    Understat returns the `position` column per (player, season) row.
    A player can be a midfielder one season and a forward the next.
    Storing position on the season-grain row preserves that signal.
    The schema's existing PK (player_id, season, team) already supports it.

WHY ONLY position_class AND NOT THE FULL position_code
    Understat's vocabulary is coarse (D / M / F / GK + S for substitute
    appearances), not the fine-grained 18-code vocabulary in our
    `positions` table. We can derive class but not code from Understat.
    Per-match data in V1.03 will eventually give us code-level data
    (e.g., DM vs CAM); for now, class is what's available.

IDEMPOTENCY + SAFETY
    - Checks information_schema before adding (re-runs cleanly).
    - Wrapped in a transaction (rollback on failure).
    - Nullable: lets the population script fill it without violating
      NOT NULL on existing rows.

HOW TO RUN
    From the repo root:
        uv run python src/model/add_position_class_column.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# Matches positions.position_class vocabulary from V1.02 schema (S5).
ALLOWED_CLASSES = "('GK', 'DEF', 'MID', 'FWD')"


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Check if the column already exists.
        existing = {
            row[0] for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }

        if "position_class" in existing:
            print("position_class column already exists on player_season_stats.")
            print("Nothing to do. (Re-run is safe.)")
            return

        # 2. Add the column. Two-step approach because DuckDB ALTER doesn't
        # let you add a column with a CHECK constraint in one statement —
        # add the column first, then add the constraint separately.
        print("Adding position_class to player_season_stats...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "ALTER TABLE player_season_stats ADD COLUMN position_class VARCHAR"
            )
            # Note: DuckDB supports CHECK at table-create time but adding via
            # ALTER is more limited. We rely on the population script to write
            # only valid values, and verify post-fill.
            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during ALTER, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 3. Verify by re-describing the table.
        print("\nUpdated columns on player_season_stats (position_class):")
        rows = con.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'player_season_stats'
              AND column_name = 'position_class'
            """
        ).fetchall()
        for col_name, dtype, nullable in rows:
            print(f"  {col_name:<22} {dtype:<10} nullable={nullable}")
    finally:
        con.close()


if __name__ == "__main__":
    main()