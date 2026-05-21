"""
V1.02 modeling — STEP 1: schema patch for shrunk rating columns.

WHAT THIS DOES
    Adds two new DOUBLE columns to player_season_stats:
      shrunk_form        — per-row Bayesian-shrunk rating (captures form).
      shrunk_consistency — career-aggregate shrunk rating (captures consistency).

    Both columns are nullable (the population script in step 2 fills them).
    Existing data is untouched. Operation is wrapped in a transaction and
    idempotency-guarded: if the columns already exist, the script exits
    cleanly without error.

WHY SPLIT FROM THE POPULATION SCRIPT
    Schema changes and value calculations are different concerns. If a
    column already exists from a previous attempt, we want a clear "already
    done" message, not a confusing ALTER error mid-math. Two commits, two
    intents.

HOW TO RUN
    From the repo root:
        uv run python src/model/add_shrinkage_columns.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# The columns we want on player_season_stats. Both nullable so adding them
# to a populated table doesn't violate constraints; step 2 fills them in.
NEW_COLUMNS = [
    ("shrunk_form",        "DOUBLE"),
    ("shrunk_consistency", "DOUBLE"),
]


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Check current schema. DuckDB's information_schema lists every
        # column on every table — we look up player_season_stats and see
        # which of our target columns are already there.
        existing = {
            row[0] for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }

        to_add = [(name, sqltype) for name, sqltype in NEW_COLUMNS
                  if name not in existing]

        if not to_add:
            print("Both shrinkage columns already exist on player_season_stats.")
            print("Nothing to do. (Re-run is safe.)")
            return

        # 2. Add only the missing columns. Wrap in a transaction so a
        # failure mid-way leaves the table unchanged.
        print(f"Adding {len(to_add)} column(s) to player_season_stats:")
        con.execute("BEGIN TRANSACTION")
        try:
            for name, sqltype in to_add:
                print(f"  + {name} {sqltype}")
                con.execute(
                    f"ALTER TABLE player_season_stats ADD COLUMN {name} {sqltype}"
                )
            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during ALTER, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 3. Verify by re-describing the table and showing the new columns.
        print("\nUpdated columns on player_season_stats:")
        rows = con.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'player_season_stats'
              AND column_name IN ('shrunk_form', 'shrunk_consistency')
            ORDER BY column_name
            """
        ).fetchall()
        for col_name, dtype, nullable in rows:
            print(f"  {col_name:<22} {dtype:<10} nullable={nullable}")
    finally:
        con.close()


if __name__ == "__main__":
    main()