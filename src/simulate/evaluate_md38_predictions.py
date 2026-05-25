"""
V1.03 modeling — S14 STEP 3: MD38 evaluation runner.

WHAT THIS DOES
    For each MD38 fixture × {B1.2, B2}, compute:
      - log_loss_scoreline  = -log(P(actual_home_goals, actual_away_goals))
      - log_loss_outcome    = -log(P(actual_outcome))
      - brier_outcome       = sum((p_i - I_i)^2) over H/D/A classes

    Joins md38_predictions_b12 (predictions) + md38_score_grid_b12
    (grid cell for actual scoreline) + team_match_stats (actuals).
    Writes 20 rows to md38_evaluation_b12_b2 (10 fixtures × 2 models).

    Then prints aggregate comparison: B1.2 vs B2 across all 10 fixtures
    on each metric. This is the headline of S14.

IDEMPOTENCY
    Wipes prior rows for the two model_versions on MD38 fixtures, then
    inserts fresh. Re-running cleanly replaces the evaluation set.

ACTUALS SOURCE
    team_match_stats with side='home' gives home_goals, opponent_goals
    in one row. We join via fixture_id -> games.match_date/teams ->
    team_match_stats.game_id. See JOIN logic in fetch_actuals().

HOW TO RUN
    From the repo root, AFTER load_md38_actuals.py has populated MD38
    rows in games + team_match_stats:
        uv run python src/simulate/evaluate_md38_predictions.py
"""

import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np

DB_PATH = Path("data/processed/worldcup.duckdb")
TARGET_SEASON = "2025-2026"
MODEL_VERSIONS = ("B1.2_v103_poisson_indep", "B2_v103_dc_post_hoc")


# ---------------------------------------------------------------------------
# Pull actuals: fixture_id -> (home_goals, away_goals, outcome)
# ---------------------------------------------------------------------------
def fetch_actuals(con):
    """
    Join the fixtures table (which has fixture_id) to games (which has
    game_id) on home_team + away_team + match_date, then to team_match_stats
    (home side) for the goal counts.

    Returns dict: {fixture_id: (home_goals, away_goals, outcome_char)}
    where outcome_char ∈ {'H', 'D', 'A'}.
    """
    rows = con.execute("""
        SELECT
            f.fixture_id,
            t.goals AS home_goals,
            t.opponent_goals AS away_goals
        FROM fixtures f
        JOIN games g
            ON g.season = f.season
           AND g.match_date = f.match_date
           AND g.home_team = f.home_team
           AND g.away_team = f.away_team
        JOIN team_match_stats t
            ON t.game_id = g.game_id
           AND t.side = 'home'
        WHERE f.matchday = 38 AND f.season = ?
        ORDER BY f.fixture_id
    """, [TARGET_SEASON]).fetchall()

    actuals = {}
    for fixture_id, home_goals, away_goals in rows:
        if home_goals > away_goals:
            outcome = "H"
        elif home_goals < away_goals:
            outcome = "A"
        else:
            outcome = "D"
        actuals[fixture_id] = (int(home_goals), int(away_goals), outcome)
    return actuals


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Fetch actuals via fixture_id join.
        actuals = fetch_actuals(con)
        if len(actuals) != 10:
            raise SystemExit(
                f"Expected 10 MD38 actuals, found {len(actuals)}. "
                f"Has load_md38_actuals.py been run?"
            )
        print(f"Loaded {len(actuals)} MD38 actuals.")

        # 2. For each (fixture, model_version), pull prediction row + grid
        # cell, compute metrics. Build up rows for batch insert.
        eval_rows = []
        for model_version in MODEL_VERSIONS:
            print(f"\nEvaluating {model_version}...")
            for fixture_id, (hg, ag, outcome) in actuals.items():
                # Pull summary row.
                pred = con.execute("""
                    SELECT p_home_win, p_draw, p_away_win
                    FROM md38_predictions_b12
                    WHERE fixture_id = ? AND model_version = ?
                """, [fixture_id, model_version]).fetchone()
                if pred is None:
                    raise SystemExit(
                        f"No prediction for {fixture_id} under "
                        f"{model_version}. Has the prediction script "
                        f"been run?"
                    )
                p_h, p_d, p_a = pred

                # Pull P(actual scoreline) from grid. Will be in 0..7;
                # for MD38 we verified no goals >= 8 (actuals max is
                # West Ham 3-0 and Brighton 0-3).
                grid_row = con.execute("""
                    SELECT probability FROM md38_score_grid_b12
                    WHERE fixture_id = ? AND model_version = ?
                      AND home_goals = ? AND away_goals = ?
                """, [fixture_id, model_version, hg, ag]).fetchone()
                if grid_row is None:
                    raise SystemExit(
                        f"No grid cell for ({hg}, {ag}) on {fixture_id} "
                        f"under {model_version}."
                    )
                p_actual_scoreline = float(grid_row[0])

                # p_actual_outcome depends on which outcome happened.
                if outcome == "H":
                    p_actual_outcome = p_h
                elif outcome == "D":
                    p_actual_outcome = p_d
                else:  # 'A'
                    p_actual_outcome = p_a

                # Metrics.
                log_loss_scoreline = -np.log(p_actual_scoreline)
                log_loss_outcome = -np.log(p_actual_outcome)
                # Brier on H/D/A: sum((p - indicator)^2) for each class.
                # Indicator is 1 for the actual outcome, 0 otherwise.
                ind_h = 1.0 if outcome == "H" else 0.0
                ind_d = 1.0 if outcome == "D" else 0.0
                ind_a = 1.0 if outcome == "A" else 0.0
                brier = ((p_h - ind_h) ** 2 +
                         (p_d - ind_d) ** 2 +
                         (p_a - ind_a) ** 2)

                eval_rows.append((
                    fixture_id, model_version,
                    hg, ag, outcome,
                    p_h, p_d, p_a,
                    p_actual_scoreline, p_actual_outcome,
                    float(log_loss_scoreline),
                    float(log_loss_outcome),
                    float(brier),
                ))

        # 3. Write in transaction. Wipe prior rows for these
        # (fixture, model_version) tuples first.
        print(f"\nBeginning transaction...")
        con.execute("BEGIN TRANSACTION")
        try:
            fixture_ids = sorted(actuals.keys())
            placeholders = ",".join(["?"] * len(fixture_ids))
            for mv in MODEL_VERSIONS:
                con.execute(
                    f"""
                    DELETE FROM md38_evaluation_b12_b2
                    WHERE model_version = ?
                      AND fixture_id IN ({placeholders})
                    """,
                    [mv] + fixture_ids,
                )
            evaluated_at = datetime.now()
            print(f"  Evaluation timestamp: {evaluated_at.isoformat()}")

            con.executemany(
                """
                INSERT INTO md38_evaluation_b12_b2 (
                    fixture_id, model_version,
                    actual_home_goals, actual_away_goals, actual_outcome,
                    p_home_win, p_draw, p_away_win,
                    p_actual_scoreline, p_actual_outcome,
                    log_loss_scoreline, log_loss_outcome, brier_outcome,
                    evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [row + (evaluated_at,) for row in eval_rows],
            )
            print(f"  Inserted {len(eval_rows)} evaluation rows.")
            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            con.execute("ROLLBACK")
            raise

        # 4. Per-fixture breakdown.
        print(f"\n{'='*128}")
        print(f"PER-FIXTURE EVALUATION (B1.2 vs B2)")
        print(f"{'='*128}")
        print(con.execute("""
            SELECT
                e.fixture_id,
                e.actual_home_goals || '-' || e.actual_away_goals AS actual,
                e.actual_outcome AS res,
                e.model_version,
                ROUND(e.p_actual_outcome * 100, 1) AS pct_outcome,
                ROUND(e.p_actual_scoreline * 100, 2) AS pct_score,
                ROUND(e.log_loss_outcome, 3) AS ll_outcome,
                ROUND(e.log_loss_scoreline, 3) AS ll_score,
                ROUND(e.brier_outcome, 3) AS brier
            FROM md38_evaluation_b12_b2 e
            ORDER BY e.fixture_id, e.model_version
        """).fetchdf().to_string())

        # 5. Aggregate comparison.
        print(f"\n{'='*128}")
        print(f"AGGREGATE COMPARISON: B1.2 vs B2 across 10 MD38 fixtures")
        print(f"  (lower = better for all three metrics)")
        print(f"{'='*128}")
        print(con.execute("""
            SELECT
                model_version,
                ROUND(SUM(log_loss_scoreline), 3) AS total_ll_scoreline,
                ROUND(AVG(log_loss_scoreline), 3) AS avg_ll_scoreline,
                ROUND(SUM(log_loss_outcome), 3)   AS total_ll_outcome,
                ROUND(AVG(log_loss_outcome), 3)   AS avg_ll_outcome,
                ROUND(SUM(brier_outcome), 3)      AS total_brier,
                ROUND(AVG(brier_outcome), 3)      AS avg_brier
            FROM md38_evaluation_b12_b2
            GROUP BY model_version
            ORDER BY model_version
        """).fetchdf().to_string())

        # 6. Head-to-head delta.
        print(f"\n{'='*128}")
        print(f"HEAD-TO-HEAD DELTA (B2 - B1.2, negative = B2 wins)")
        print(f"{'='*128}")
        print(con.execute("""
            WITH agg AS (
                SELECT model_version,
                       SUM(log_loss_scoreline) AS ll_s,
                       SUM(log_loss_outcome) AS ll_o,
                       SUM(brier_outcome) AS br
                FROM md38_evaluation_b12_b2
                GROUP BY model_version
            ),
            b12 AS (SELECT * FROM agg WHERE model_version='B1.2_v103_poisson_indep'),
            b2  AS (SELECT * FROM agg WHERE model_version='B2_v103_dc_post_hoc')
            SELECT
                ROUND(b2.ll_s - b12.ll_s, 4) AS delta_ll_scoreline,
                ROUND(b2.ll_o - b12.ll_o, 4) AS delta_ll_outcome,
                ROUND(b2.br - b12.br, 4)     AS delta_brier
            FROM b12, b2
        """).fetchdf().to_string())

        # 7. Per-fixture B2 vs B1.2 deltas — which fixtures did B2 help on?
        print(f"\n{'='*128}")
        print(f"PER-FIXTURE: B2 - B1.2 ON LOG-LOSS SCORELINE")
        print(f"  (negative = B2 assigned more probability to actual scoreline)")
        print(f"{'='*128}")
        print(con.execute("""
            SELECT
                b12.fixture_id,
                b12.actual_home_goals || '-' || b12.actual_away_goals AS actual,
                b12.actual_outcome AS res,
                ROUND(b12.log_loss_scoreline, 3) AS b12_ll,
                ROUND(b2.log_loss_scoreline, 3)  AS b2_ll,
                ROUND(b2.log_loss_scoreline - b12.log_loss_scoreline, 4) AS delta
            FROM md38_evaluation_b12_b2 b12
            JOIN md38_evaluation_b12_b2 b2
                ON b12.fixture_id = b2.fixture_id
            WHERE b12.model_version = 'B1.2_v103_poisson_indep'
              AND b2.model_version = 'B2_v103_dc_post_hoc'
            ORDER BY delta
        """).fetchdf().to_string())
    finally:
        con.close()


if __name__ == "__main__":
    main()