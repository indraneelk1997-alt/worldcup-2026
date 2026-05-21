"""
V1.02 modeling — STEP 4 (a) — REVISED in S8 afternoon.

WHAT THIS DOES
    Creates the `best_xi` table that holds top-3 realistic XIs per
    (team, season), one row per (formation, rank, slot). Rank=1 is the
    best-fit formation for that team's roster; rank=2 is second best;
    rank=3 third.

EVOLUTION FROM S8 MORNING
    The original best_xi (S8 morning) stored ONE XI per (team, season)
    using a single arbitrary formation, with the now-known-bad 1/2/4
    multipliers. This revised version:
      - Adds `formation` to the PK so we can store multiple formations
        per team-season.
      - Adds `rank` (1-3) so we keep only the top 3 best-fit formations.
      - Same selection_score semantics, but the score now uses a more
        nuanced computation (Hungarian assignment + slot bonus for
        hybrid players); see select_best_xi.py for details.

SCHEMA
    Composite PK: (season, team, formation, rank, slot_no).
    - season + team   identifies the team-season
    - formation       identifies which formation this XI is for
    - rank            1=best fit, 2=second, 3=third (lower=better)
    - slot_no         1-11, position within the XI
    - player_id       FK to players
    - position_class  denormalized for query convenience
    - minutes         denormalized (useful for GK rationale)
    - selection_score NULL for GK, computed for outfielders
    - total_xi_score  the formation's total (sum of all selection_scores).
                      Denormalized onto every row of the XI for easy
                      filtering. Same value for slots 1-11 of one XI.

WHY total_xi_score IS ON EVERY ROW
    Could be normalized into a separate xi_meta table, but for V1.02
    it's easier to ORDER BY total_xi_score WHERE rank=1 directly
    without an extra join. Cost: 11x duplication of one DOUBLE per XI.
    Trivial at this scale.

IDEMPOTENCY
    CREATE TABLE IF NOT EXISTS. Re-running the selection script
    DELETEs by (season) then INSERTs.

HOW TO RUN
    From the repo root:
        # If a previous best_xi from S8 morning exists, drop it first:
        uv run python -c "import duckdb; con=duckdb.connect('data/processed/worldcup.duckdb'); con.execute('DROP TABLE IF EXISTS best_xi'); con.close()"
        uv run python src/model/best_xi_schema.py
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

        if "best_xi" in existing:
            # Check whether it's already the NEW schema by looking for
            # the `formation` column. If yes, no-op. If no, complain
            # loudly so the user knows to drop it first.
            cols = {
                r[0] for r in con.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'best_xi'
                    """
                ).fetchall()
            }
            if "formation" in cols and "rank" in cols:
                print("best_xi already on new schema. Nothing to do.")
                return
            raise SystemExit(
                "best_xi exists but is on the OLD schema (no `formation` "
                "or `rank` column). Drop it first:\n"
                "  uv run python -c \"import duckdb; "
                "con=duckdb.connect('data/processed/worldcup.duckdb'); "
                "con.execute('DROP TABLE IF EXISTS best_xi'); con.close()\""
            )

        print("Creating best_xi table (new schema)...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("""
                CREATE TABLE best_xi (
                    season           VARCHAR NOT NULL,
                    team             VARCHAR NOT NULL,
                    formation        VARCHAR NOT NULL REFERENCES formations(formation),
                    rank             INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
                    slot_no          INTEGER NOT NULL CHECK (slot_no BETWEEN 1 AND 11),
                    player_id        INTEGER NOT NULL REFERENCES players(player_id),
                    position_class   VARCHAR NOT NULL CHECK (position_class IN ('GK','DEF','MID','FWD')),
                    minutes          INTEGER NOT NULL,
                    selection_score  DOUBLE,
                    total_xi_score   DOUBLE NOT NULL,
                    PRIMARY KEY (season, team, formation, rank, slot_no)
                )
            """)
            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during CREATE, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        print("\nbest_xi columns:")
        rows = con.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'best_xi'
            ORDER BY ordinal_position
            """
        ).fetchall()
        for col_name, dtype, nullable in rows:
            print(f"  {col_name:<18} {dtype:<10} nullable={nullable}")
    finally:
        con.close()


if __name__ == "__main__":
    main()