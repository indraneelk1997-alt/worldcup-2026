"""
V1.03 modeling — S14 STEP 2: MD38 evaluation table schema.

WHAT THIS DOES
    Creates md38_evaluation_b12_b2: one row per (fixture, model_version)
    storing log-loss + Brier + reference fields for the post-MD38
    comparison between B1.2 and B2 predictions vs actuals.

    Aggregate stats (B1.2 vs B2 total log-loss etc.) are NOT stored —
    they're derived on demand from this 20-row table via GROUP BY.

WHY THIS TABLE
    - Persistent provenance: the comparison is replayable and queryable
      months later without rerunning the evaluation script.
    - Composite PK (fixture_id, model_version) allows future models
      (e.g. B3 if it ships) to be added under new model_version strings.
    - Reference columns (actual scoreline, predicted H/D/A, predicted
      P(actual scoreline)) make the row self-contained for inspection.

FK STRATEGY
    fixture_id -> fixtures(fixture_id)
    (fixture_id, model_version) -> md38_predictions_b12 (composite)

    The second FK is the integrity contract: an evaluation row cannot
    exist without a matching pre-registered prediction. This is the
    whole point of S14 — comparing locked-in predictions to actuals.

HOW TO RUN
    From the repo root:
        uv run python src/load/create_md38_evaluation_table.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS md38_evaluation_b12_b2 (
                fixture_id              VARCHAR     NOT NULL,
                model_version           VARCHAR     NOT NULL,

                -- Actual outcome (denormalized from team_match_stats for
                -- self-contained inspection).
                actual_home_goals       INTEGER     NOT NULL,
                actual_away_goals       INTEGER     NOT NULL,
                actual_outcome          VARCHAR     NOT NULL,
                                            -- 'H', 'D', or 'A'

                -- Predicted distribution (denormalized from
                -- md38_predictions_b12 for inspection without joins).
                p_home_win              DOUBLE      NOT NULL,
                p_draw                  DOUBLE      NOT NULL,
                p_away_win              DOUBLE      NOT NULL,
                p_actual_scoreline      DOUBLE      NOT NULL,
                                            -- the grid cell prob for
                                            -- (actual_home_goals,
                                            --  actual_away_goals)
                p_actual_outcome        DOUBLE      NOT NULL,
                                            -- p_home_win / p_draw /
                                            -- p_away_win, depending on
                                            -- actual_outcome

                -- The metrics.
                log_loss_scoreline      DOUBLE      NOT NULL,
                                            -- -log(p_actual_scoreline)
                log_loss_outcome        DOUBLE      NOT NULL,
                                            -- -log(p_actual_outcome)
                brier_outcome           DOUBLE      NOT NULL,
                                            -- sum((p_i - I_i)^2) over
                                            -- the 3 H/D/A classes

                evaluated_at            TIMESTAMP   NOT NULL
                                            DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (fixture_id, model_version),
                FOREIGN KEY (fixture_id) REFERENCES fixtures (fixture_id),
                FOREIGN KEY (fixture_id, model_version)
                    REFERENCES md38_predictions_b12 (fixture_id,
                                                     model_version)
            )
        """)

        # Verify.
        cols = con.execute(
            "DESCRIBE md38_evaluation_b12_b2"
        ).fetchall()
        print(f"Created (or already existed): md38_evaluation_b12_b2")
        print(f"  {len(cols)} columns:")
        for c in cols:
            null_str = "NULL" if c[2] == "YES" else "NOT NULL"
            pk_str = " (PK)" if c[3] == "PRI" else ""
            print(f"    {c[0]:<22} {c[1]:<12} {null_str}{pk_str}")
    finally:
        con.close()


if __name__ == "__main__":
    main()