"""
V1.03 modeling — B2c: MD38 pre-registered predictions with Dixon-Coles
                       tau correction (Path Z: post-processor on B1.2).

WHAT THIS DOES
    For each of the 10 MD38 fixtures (PL 2025-26, kickoff May 24 2026):
      1. Calls predict_xg_v103.predict_xg() to get B1.2 (xG_home, xG_away).
         IDENTICAL B1.2 inputs as run_md38_predictions_b12.py.
      2. Builds 8x8 truncated, renormalized independent-Poisson grid.
      3. Applies Dixon-Coles tau correction with rho from
         model_parameters_v103 (parameter_name='dc_rho',
         model_version='B2_v103_dc_post_hoc'), then renormalizes.
      4. Computes summary stats from the corrected grid.
      5. Writes rows to md38_predictions_b12 + md38_score_grid_b12
         under model_version='B2_v103_dc_post_hoc'. The composite PK
         on both tables lets these coexist with the B1.2 rows.

WHY SAME TABLES
    Composite PK (fixture_id, model_version) was designed precisely so
    B2 predictions could live next to B1.2 in the same tables — same
    schema, same diagnostic columns, easy joins for comparison queries.

IDEMPOTENCY
    Wipes prior rows for model_version='B2_v103_dc_post_hoc' on MD38
    fixtures before writing. B1.2 rows are untouched.

HOW TO RUN
    From the repo root, BEFORE May 24 kickoff:
        uv run python src/simulate/run_md38_predictions_b2.py
"""

import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
from scipy.stats import poisson

# Make src.* importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.model.predict_xg_v103 import predict_xg  # noqa: E402

DB_PATH = Path("data/processed/worldcup.duckdb")
TARGET_SEASON = "2025-2026"
MODEL_VERSION = "B2_v103_dc_post_hoc"
RHO_PARAM_NAME = "dc_rho"
MAX_GOALS = 7  # cap per side; grid is 8x8


# ---------------------------------------------------------------------------
# Core: B1.2 xG -> Poisson grid -> DC-corrected grid + summary
# ---------------------------------------------------------------------------
def build_poisson_grid(xg_home: float, xg_away: float):
    """Truncated, renormalized 8x8 independent-Poisson grid + truncation mass."""
    if xg_home <= 0 or xg_away <= 0:
        raise ValueError(
            f"xG must be positive. Got xg_home={xg_home}, xg_away={xg_away}."
        )
    ks = np.arange(MAX_GOALS + 1)
    p_home = poisson.pmf(ks, mu=xg_home)
    p_away = poisson.pmf(ks, mu=xg_away)
    raw = np.outer(p_home, p_away)
    total = raw.sum()
    prob_mass_truncated = float(1.0 - total)
    return raw / total, prob_mass_truncated


def apply_dc_correction(grid: np.ndarray,
                         xg_home: float,
                         xg_away: float,
                         rho: float) -> np.ndarray:
    """
    Apply Dixon-Coles tau correction to a renormalized Poisson grid.
    Modifies only the four low-score cells; renormalizes the result.

    Reference: Dixon & Coles 1997, Modelling Association Football Scores.
    """
    corrected = grid.copy()
    corrected[0, 0] *= 1.0 - xg_home * xg_away * rho
    corrected[0, 1] *= 1.0 + xg_home * rho
    corrected[1, 0] *= 1.0 + xg_away * rho
    corrected[1, 1] *= 1.0 - rho
    corrected = np.maximum(corrected, 1e-15)
    corrected /= corrected.sum()
    return corrected


def summarize_grid(grid: np.ndarray):
    """Outcome probs, expected goals, modal scoreline — same as B1.2 runner."""
    n = grid.shape[0]
    ks = np.arange(n)

    p_home_win = float(np.tril(grid, k=-1).sum())
    p_draw = float(np.trace(grid))
    p_away_win = float(np.triu(grid, k=1).sum())

    total = p_home_win + p_draw + p_away_win
    if not np.isclose(total, 1.0, atol=1e-9):
        raise ValueError(
            f"Outcome probs don't sum to 1: {total}. Grid sum: {grid.sum()}."
        )

    expected_home_goals = float((grid.sum(axis=1) * ks).sum())
    expected_away_goals = float((grid.sum(axis=0) * ks).sum())

    flat_idx = int(np.argmax(grid))
    ml_home, ml_away = divmod(flat_idx, n)
    ml_prob = float(grid[ml_home, ml_away])

    return {
        "p_home_win": p_home_win,
        "p_draw": p_draw,
        "p_away_win": p_away_win,
        "expected_home_goals": expected_home_goals,
        "expected_away_goals": expected_away_goals,
        "most_likely_score_home": int(ml_home),
        "most_likely_score_away": int(ml_away),
        "most_likely_score_prob": ml_prob,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Load calibrated rho. Fail loudly if missing.
        rho_row = con.execute(
            """
            SELECT value, n_matches_used, log_likelihood, ll_vs_baseline,
                   calibrated_at
            FROM model_parameters_v103
            WHERE parameter_name = ? AND model_version = ?
            """,
            [RHO_PARAM_NAME, MODEL_VERSION],
        ).fetchone()
        if rho_row is None:
            raise SystemExit(
                f"No rho found in model_parameters_v103 for "
                f"parameter_name='{RHO_PARAM_NAME}', "
                f"model_version='{MODEL_VERSION}'. Run "
                f"src/model/calibrate_dc_rho_v103.py first."
            )
        rho, n_cal, ll_opt, ll_improvement, calibrated_at = rho_row
        print(f"Using rho={rho:+.6f} "
              f"(calibrated on {n_cal} matches, "
              f"log-lik {ll_opt:.2f}, "
              f"+{ll_improvement:.2f} vs indep Poisson, "
              f"calibrated_at={calibrated_at}).")

        # 2. Fetch MD38 fixtures.
        fixtures = con.execute("""
            SELECT fixture_id, home_team, away_team
            FROM fixtures
            WHERE matchday = 38 AND season = ?
            ORDER BY fixture_id
        """, [TARGET_SEASON]).fetchall()
        if not fixtures:
            raise SystemExit(
                f"No MD38 fixtures in DB for {TARGET_SEASON}."
            )
        print(f"\nFound {len(fixtures)} MD38 fixtures.\n")

        # 3. Build predictions in memory (fail-fast).
        print(f"Computing B1.2 xG, Poisson grid, DC correction "
              f"(model_version='{MODEL_VERSION}')...")
        predictions = []
        for fixture_id, home, away in fixtures:
            pred = predict_xg(con, home, away, TARGET_SEASON)
            poisson_grid, prob_mass_truncated = build_poisson_grid(
                pred.xg_home, pred.xg_away
            )
            dc_grid = apply_dc_correction(
                poisson_grid, pred.xg_home, pred.xg_away, rho
            )
            summary = summarize_grid(dc_grid)
            predictions.append({
                "fixture_id": fixture_id,
                "home_team": home,
                "away_team": away,
                "xg_home": pred.xg_home,
                "xg_away": pred.xg_away,
                "grid": dc_grid,
                "prob_mass_truncated": prob_mass_truncated,
                **summary,
            })

        # 4. Write in a single transaction. Wipe prior B2 rows for
        # these fixtures first (idempotency).
        fixture_ids = [p["fixture_id"] for p in predictions]
        placeholders = ",".join(["?"] * len(fixture_ids))

        print(f"\nBeginning transaction...")
        con.execute("BEGIN TRANSACTION")
        try:
            prior_grid = con.execute(
                f"""
                SELECT COUNT(*) FROM md38_score_grid_b12
                WHERE model_version = ?
                  AND fixture_id IN ({placeholders})
                """,
                [MODEL_VERSION] + fixture_ids,
            ).fetchone()[0]
            prior_summary = con.execute(
                f"""
                SELECT COUNT(*) FROM md38_predictions_b12
                WHERE model_version = ?
                  AND fixture_id IN ({placeholders})
                """,
                [MODEL_VERSION] + fixture_ids,
            ).fetchone()[0]
            if prior_grid or prior_summary:
                print(f"  Wiping {prior_summary} prior B2 summary rows + "
                      f"{prior_grid} prior B2 grid rows...")
                con.execute(
                    f"""
                    DELETE FROM md38_score_grid_b12
                    WHERE model_version = ?
                      AND fixture_id IN ({placeholders})
                    """,
                    [MODEL_VERSION] + fixture_ids,
                )
                con.execute(
                    f"""
                    DELETE FROM md38_predictions_b12
                    WHERE model_version = ?
                      AND fixture_id IN ({placeholders})
                    """,
                    [MODEL_VERSION] + fixture_ids,
                )

            predicted_at = datetime.now()
            print(f"  Pre-registration timestamp: {predicted_at.isoformat()}")

            summary_rows = [
                (
                    p["fixture_id"], p["home_team"], p["away_team"],
                    p["xg_home"], p["xg_away"],
                    p["p_home_win"], p["p_draw"], p["p_away_win"],
                    p["expected_home_goals"], p["expected_away_goals"],
                    p["most_likely_score_home"], p["most_likely_score_away"],
                    p["most_likely_score_prob"],
                    p["prob_mass_truncated"],
                    MODEL_VERSION, predicted_at,
                )
                for p in predictions
            ]
            con.executemany(
                """
                INSERT INTO md38_predictions_b12 (
                    fixture_id, home_team, away_team,
                    xg_home, xg_away,
                    p_home_win, p_draw, p_away_win,
                    expected_home_goals, expected_away_goals,
                    most_likely_score_home, most_likely_score_away,
                    most_likely_score_prob,
                    prob_mass_truncated,
                    model_version, predicted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                summary_rows,
            )

            grid_rows = []
            for p in predictions:
                grid = p["grid"]
                for i in range(MAX_GOALS + 1):
                    for j in range(MAX_GOALS + 1):
                        grid_rows.append(
                            (p["fixture_id"], MODEL_VERSION,
                             i, j, float(grid[i, j]))
                        )
            con.executemany(
                """
                INSERT INTO md38_score_grid_b12 (
                    fixture_id, model_version,
                    home_goals, away_goals, probability
                ) VALUES (?, ?, ?, ?, ?)
                """,
                grid_rows,
            )
            print(f"  Inserted {len(summary_rows)} summary rows + "
                  f"{len(grid_rows)} grid rows.")

            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            print("!!! Error during writes, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 5. Print B1.2 vs B2 comparison side-by-side.
        print(f"\n{'='*120}")
        print(f"MD38 B1.2 vs B2 SIDE-BY-SIDE  (rho = {rho:+.6f})")
        print(f"{'='*120}")
        print(f"{'home':<20} {'away':<24}  "
              f"{'B1.2 H/D/A':>20}  {'B2 H/D/A':>20}  "
              f"{'B1.2 mod':>9}  {'B2 mod':>8}")
        print("-" * 120)
        for p in predictions:
            b12_row = con.execute(
                """
                SELECT p_home_win, p_draw, p_away_win,
                       most_likely_score_home, most_likely_score_away
                FROM md38_predictions_b12
                WHERE fixture_id = ?
                  AND model_version = 'B1.2_v103_poisson_indep'
                """,
                [p["fixture_id"]],
            ).fetchone()
            b12_modal = f"{b12_row[3]}-{b12_row[4]}"
            b2_modal = f"{p['most_likely_score_home']}-{p['most_likely_score_away']}"
            print(
                f"{p['home_team'][:20]:<20} {p['away_team'][:24]:<24}  "
                f"{b12_row[0]*100:>5.1f}/{b12_row[1]*100:>4.1f}/"
                f"{b12_row[2]*100:>5.1f}%  "
                f"{p['p_home_win']*100:>5.1f}/{p['p_draw']*100:>4.1f}/"
                f"{p['p_away_win']*100:>5.1f}%  "
                f"{b12_modal:>9}  {b2_modal:>8}"
            )

        max_trunc = max(p["prob_mass_truncated"] for p in predictions)
        print(f"\nMax prob_mass_truncated: {max_trunc:.2e}")
    finally:
        con.close()


if __name__ == "__main__":
    main()