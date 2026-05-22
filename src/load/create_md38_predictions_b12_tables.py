"""
V1.03 modeling — Step 1 of MD38 B1.2 pre-registered predictions.

WHAT THIS DOES
    Creates two tables for storing MD38 B1.2 predictions:

      md38_predictions_b12
          One row per (fixture, model_version). Stores B1.2 xG inputs and
          derived independent-Poisson summary statistics.

      md38_score_grid_b12
          One row per (fixture, home_goals, away_goals, model_version).
          The full 8x8 truncated+renormalized Poisson score distribution.

    Idempotent: CREATE TABLE IF NOT EXISTS. Re-running this script is safe.
    Does NOT write any data — schema only.

WHY TWO TABLES
    Summary stats (P(H/D/A), expected goals) live in md38_predictions_b12
    for cheap aggregate queries. The full score grid lives in
    md38_score_grid_b12 so we can compute log-loss / Brier score against
    the actual scoreline after MD38 plays out (May 24, 2026), and so we
    have an apples-to-apples comparison surface when B2 (Dixon-Coles)
    ships later.

MODEL VERSION STRING
    'B1.2_v103_poisson_indep' — distinguishes this from future B2
    Dixon-Coles predictions on the same fixtures.

HOW TO RUN
    From the repo root:
        uv run python src/load/create_md38_predictions_b12_tables.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # Summary table — one row per (fixture, model_version).
        con.execute("""
            CREATE TABLE IF NOT EXISTS md38_predictions_b12 (
                fixture_id              VARCHAR     NOT NULL,
                home_team               VARCHAR     NOT NULL,
                away_team               VARCHAR     NOT NULL,
                xg_home                 DOUBLE      NOT NULL,
                xg_away                 DOUBLE      NOT NULL,
                p_home_win              DOUBLE      NOT NULL,
                p_draw                  DOUBLE      NOT NULL,
                p_away_win              DOUBLE      NOT NULL,
                expected_home_goals     DOUBLE      NOT NULL,
                expected_away_goals     DOUBLE      NOT NULL,
                most_likely_score_home  INTEGER     NOT NULL,
                most_likely_score_away  INTEGER     NOT NULL,
                most_likely_score_prob  DOUBLE      NOT NULL,
                prob_mass_truncated     DOUBLE      NOT NULL,
                model_version           VARCHAR     NOT NULL,
                predicted_at            TIMESTAMP   NOT NULL
                                            DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (fixture_id, model_version),
                FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id)
            )
        """)

        # Full score grid — one row per (fixture, home_goals, away_goals,
        # model_version). Probabilities are post-truncation, renormalized
        # to sum to 1 per (fixture, model_version).
        con.execute("""
            CREATE TABLE IF NOT EXISTS md38_score_grid_b12 (
                fixture_id      VARCHAR     NOT NULL,
                model_version   VARCHAR     NOT NULL,
                home_goals      INTEGER     NOT NULL,
                away_goals      INTEGER     NOT NULL,
                probability     DOUBLE      NOT NULL,
                PRIMARY KEY (fixture_id, model_version,
                             home_goals, away_goals),
                FOREIGN KEY (fixture_id, model_version)
                    REFERENCES md38_predictions_b12 (fixture_id,
                                                     model_version)
            )
        """)

        # Verify.
        print("Created (or already existed):")
        for tbl in ("md38_predictions_b12", "md38_score_grid_b12"):
            cols = con.execute(f"DESCRIBE {tbl}").fetchall()
            print(f"\n{tbl}: {len(cols)} columns")
            for c in cols:
                print(f"  {c[0]:<26} {c[1]:<12} "
                      f"{'NULL' if c[2] == 'YES' else 'NOT NULL'}"
                      f"{' (PK)' if c[3] == 'PRI' else ''}")
    finally:
        con.close()


if __name__ == "__main__":
    main()