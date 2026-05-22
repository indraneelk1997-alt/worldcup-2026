"""
V1.03 modeling — Step 2 of MD38 B1.2 pre-registered predictions.

WHAT THIS DOES
    For each of the 10 MD38 fixtures (PL 2025-2026, played May 24, 2026):
      1. Calls predict_xg_v103.predict_xg() to get B1.2 (xG_home, xG_away).
      2. Builds an 8x8 independent-Poisson score grid (home_goals 0..7,
         away_goals 0..7) via scipy.stats.poisson.pmf outer product.
      3. Records prob_mass_truncated = 1 - sum(grid), then renormalizes
         the grid to sum to 1.
      4. Derives summary stats from the renormalized grid:
            P(home win), P(draw), P(away win)
            expected_home_goals, expected_away_goals  (post-renorm means)
            most_likely_score_(home,away,prob)
      5. Writes one row to md38_predictions_b12 + 64 rows to
         md38_score_grid_b12 per fixture, all in a single transaction.

IDEMPOTENCY
    Wipes any prior rows for model_version='B1.2_v103_poisson_indep' on
    MD38 fixtures before writing. Re-running cleanly replaces the
    prediction set. Other model_versions (e.g. future B2 Dixon-Coles)
    are untouched.

WHY PRE-REGISTRATION
    Actuals land Sun May 24, 2026. Running this BEFORE kickoff
    timestamps the predictions in predicted_at, so the post-MD38
    writeup can claim a clean out-of-sample comparison rather than
    a fit-after-the-fact one.

HOW TO RUN
    From the repo root, BEFORE May 24 kickoff:
        uv run python src/simulate/run_md38_predictions_b12.py
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
MODEL_VERSION = "B1.2_v103_poisson_indep"
MAX_GOALS = 7  # cap per side; grid is (MAX_GOALS+1) x (MAX_GOALS+1) = 8x8


# ---------------------------------------------------------------------------
# Core: B1.2 xG -> truncated, renormalized 8x8 Poisson score grid + summary
# ---------------------------------------------------------------------------
def build_score_grid(xg_home: float, xg_away: float):
    """
    Independent-Poisson joint distribution over (home_goals, away_goals)
    with both axes truncated to 0..MAX_GOALS, then renormalized.

    Returns (grid, prob_mass_truncated) where:
      grid: 2D numpy array of shape (MAX_GOALS+1, MAX_GOALS+1).
            grid[i, j] = P(home=i, away=j) after renormalization.
            Sums to 1.0 (up to float precision).
      prob_mass_truncated: float in [0, 1). The probability mass that
            fell outside the cap BEFORE renormalization. For sane PL
            xG values (~0.5-3.0) this is essentially zero, but storing
            it makes the truncation auditable.
    """
    if xg_home <= 0 or xg_away <= 0:
        raise ValueError(
            f"xG must be positive. Got xg_home={xg_home}, xg_away={xg_away}."
        )

    ks = np.arange(MAX_GOALS + 1)  # 0..7
    p_home = poisson.pmf(ks, mu=xg_home)  # shape (8,)
    p_away = poisson.pmf(ks, mu=xg_away)  # shape (8,)

    # Outer product: independent joint distribution.
    # grid[i, j] = P(home=i) * P(away=j).
    raw_grid = np.outer(p_home, p_away)

    total = raw_grid.sum()
    prob_mass_truncated = float(1.0 - total)
    grid = raw_grid / total  # renormalize

    return grid, prob_mass_truncated


def summarize_grid(grid: np.ndarray):
    """
    Derive summary statistics from a (MAX_GOALS+1, MAX_GOALS+1)
    renormalized score grid.

    Returns a dict with:
      p_home_win, p_draw, p_away_win  (sum to 1.0)
      expected_home_goals, expected_away_goals
      most_likely_score_home, most_likely_score_away, most_likely_score_prob
    """
    n = grid.shape[0]  # MAX_GOALS+1
    ks = np.arange(n)

    # Outcome probabilities.
    p_home_win = float(np.tril(grid, k=-1).sum())  # i > j
    p_draw = float(np.trace(grid))                  # i == j
    p_away_win = float(np.triu(grid, k=1).sum())   # i < j

    # Sanity: must sum to ~1.0.
    total_outcome_prob = p_home_win + p_draw + p_away_win
    if not np.isclose(total_outcome_prob, 1.0, atol=1e-9):
        raise ValueError(
            f"Outcome probabilities don't sum to 1: "
            f"H+D+A = {total_outcome_prob}. Grid sum: {grid.sum()}."
        )

    # Expected goals (post-renormalization means).
    expected_home_goals = float((grid.sum(axis=1) * ks).sum())
    expected_away_goals = float((grid.sum(axis=0) * ks).sum())

    # Modal scoreline (argmax over flattened grid; first-found on ties).
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
        # 1. Fetch MD38 fixtures.
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
        print(f"Found {len(fixtures)} MD38 fixtures for "
              f"season {TARGET_SEASON}.\n")

        # 2. Build predictions in memory first (fail-fast: if any team
        # is missing strength data, predict_xg will raise before we
        # touch the DB).
        print(f"Computing B1.2 xG + 8x8 Poisson grids "
              f"(model_version='{MODEL_VERSION}')...")
        predictions = []  # list of dicts, one per fixture
        for fixture_id, home, away in fixtures:
            pred = predict_xg(con, home, away, TARGET_SEASON)
            grid, prob_mass_truncated = build_score_grid(
                pred.xg_home, pred.xg_away
            )
            summary = summarize_grid(grid)

            predictions.append({
                "fixture_id": fixture_id,
                "home_team": home,
                "away_team": away,
                "xg_home": pred.xg_home,
                "xg_away": pred.xg_away,
                "grid": grid,
                "prob_mass_truncated": prob_mass_truncated,
                **summary,
            })

        # 3. Write everything in a single transaction. Wipe prior
        # B1.2 rows for these fixtures first (idempotency).
        fixture_ids = [p["fixture_id"] for p in predictions]
        placeholders = ",".join(["?"] * len(fixture_ids))

        print(f"\nBeginning transaction...")
        con.execute("BEGIN TRANSACTION")
        try:
            # Wipe grid first (child), then summary (parent), per FK.
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
                print(f"  Wiping {prior_summary} prior summary rows + "
                      f"{prior_grid} prior grid rows...")
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

            # Single timestamp for all rows in this batch — they're
            # logically one pre-registration event.
            predicted_at = datetime.now()
            print(f"  Pre-registration timestamp: {predicted_at.isoformat()}")

            # Insert summary rows.
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

            # Insert grid rows. 10 fixtures * 64 cells = 640 rows.
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

        # 4. Print comparison table.
        print(f"\n{'='*108}")
        print(f"MD38 PRE-REGISTERED PREDICTIONS — {MODEL_VERSION}")
        print(f"{'='*108}")
        print(f"{'home':<20} {'away':<24} "
              f"{'xG_H':>5} {'xG_A':>5} "
              f"{'H%':>5} {'D%':>5} {'A%':>5} "
              f"{'modal':>7} {'modal%':>7}")
        print("-" * 108)
        for p in predictions:
            modal = f"{p['most_likely_score_home']}-{p['most_likely_score_away']}"
            print(
                f"{p['home_team'][:20]:<20} {p['away_team'][:24]:<24} "
                f"{p['xg_home']:>5.2f} {p['xg_away']:>5.2f} "
                f"{p['p_home_win']*100:>4.1f}% "
                f"{p['p_draw']*100:>4.1f}% "
                f"{p['p_away_win']*100:>4.1f}% "
                f"{modal:>7} "
                f"{p['most_likely_score_prob']*100:>5.1f}%"
            )

        # 5. Max truncation diagnostic.
        max_trunc = max(p["prob_mass_truncated"] for p in predictions)
        print(f"\nMax prob_mass_truncated across all fixtures: "
              f"{max_trunc:.2e}  (should be essentially zero)")
    finally:
        con.close()


if __name__ == "__main__":
    main()