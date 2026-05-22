"""
V1.03 B1.2 Step 3+4: Joint calibration of pressing exponent alpha and
home/away multipliers via 2-D grid search.

Vectorized implementation: pre-loads all team-match features into a single
dataframe, computes predictions across the full grid as numpy array math.

Grid (same as before):
  alpha           ∈ [0.0, 0.1, ..., 1.5]    (16 values)
  home_multiplier ∈ [0.90, 0.95, ..., 1.30] (9 values)
  away_multiplier ∈ [0.70, 0.75, ..., 1.10] (9 values)

Loss: MSE.

Note: predict_xg() in predict_xg_v103.py is the canonical formula. This
script reproduces it inline as vectorized numpy for speed. The two MUST
stay algebraically identical. A smoke test at the end verifies that the
vectorized prediction matches predict_xg() on one row.
"""

import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

from predict_xg_v103 import predict_xg, DB_PATH


ALPHA_GRID = np.round(np.arange(0.0, 1.51, 0.1), 2)
HOME_MULT_GRID = np.round(np.arange(0.90, 1.31, 0.05), 2)
AWAY_MULT_GRID = np.round(np.arange(0.70, 1.11, 0.05), 2)


def load_feature_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per team-match. All features pre-joined so prediction is
    pure column math.

    Columns after this:
      game_id, team, opponent, season, side, actual_xg,
      own_avg_xg_for, own_avg_ppda_pressing,
      opp_avg_xg_allowed, opp_avg_ppda_pressing,
      league_avg_xg, league_avg_ppda
    """
    df = con.execute(
        """
        SELECT
            tms.game_id,
            tms.team,
            tms.opponent,
            tms.season,
            tms.side,
            tms.xg AS actual_xg,
            own.avg_xg_for         AS own_avg_xg_for,
            own.avg_ppda_pressing  AS own_avg_ppda_pressing,
            opp.avg_xg_allowed     AS opp_avg_xg_allowed,
            opp.avg_ppda_pressing  AS opp_avg_ppda_pressing,
            la.league_avg_xg,
            la.league_avg_ppda
        FROM team_match_stats tms
        JOIN team_season_strength_v103 own
            ON own.team = tms.team AND own.season = tms.season
        JOIN team_season_strength_v103 opp
            ON opp.team = tms.opponent AND opp.season = tms.season
        JOIN league_averages_v103 la
            ON la.season = tms.season
        """
    ).df()
    return df


def predict_vectorized(
    feats: pd.DataFrame, alpha: float, home_mult: float, away_mult: float
) -> np.ndarray:
    """Vectorized version of the predict_xg formula.

    xG_team = (own_xg_for * opp_xg_allowed / league_avg_xg)
            * (opp_ppda / league_avg_ppda) ** alpha
            * side_multiplier
    """
    attack_x_defense = (
        feats["own_avg_xg_for"] * feats["opp_avg_xg_allowed"] / feats["league_avg_xg"]
    )
    pressing_mult = (
        feats["opp_avg_ppda_pressing"] / feats["league_avg_ppda"]
    ) ** alpha
    side_mult = np.where(feats["side"] == "home", home_mult, away_mult)
    return (attack_x_defense * pressing_mult * side_mult).to_numpy()


def smoke_test_vs_predict_xg(con: duckdb.DuckDBPyConnection, feats: pd.DataFrame) -> None:
    """Sanity check: the vectorized formula must match predict_xg() exactly
    on a known row. If this drifts, calibration is invalid."""
    row = feats.iloc[0]
    if row["side"] == "home":
        home, away = row["team"], row["opponent"]
    else:
        away, home = row["team"], row["opponent"]
    canonical = predict_xg(
        con, home, away, row["season"],
        alpha=0.7, home_multiplier=1.10, away_multiplier=0.90,
    )
    canonical_val = canonical.xg_home if row["side"] == "home" else canonical.xg_away

    one_row = feats.iloc[[0]]
    vectorized_val = predict_vectorized(one_row, alpha=0.7, home_mult=1.10, away_mult=0.90)[0]

    assert abs(canonical_val - vectorized_val) < 1e-9, (
        f"VECTORIZED FORMULA DIVERGED FROM predict_xg(): "
        f"canonical={canonical_val}, vectorized={vectorized_val}"
    )
    print(f"  Smoke test passed: canonical={canonical_val:.6f}, "
          f"vectorized={vectorized_val:.6f}")


def main() -> None:
    print(f"Connecting (read-only) to {DB_PATH}")
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        feats = load_feature_table(con)
        print(f"Loaded {len(feats)} team-match rows with all features pre-joined.")
        print(f"Actual xG: mean={feats['actual_xg'].mean():.3f}, "
              f"std={feats['actual_xg'].std():.3f}")

        print("\n--- Smoke test: vectorized formula vs predict_xg() ---")
        smoke_test_vs_predict_xg(con, feats)

        actuals = feats["actual_xg"].to_numpy()
        n_points = len(ALPHA_GRID) * len(HOME_MULT_GRID) * len(AWAY_MULT_GRID)
        print(f"\nGrid: {n_points} points")

        results = []
        for alpha in ALPHA_GRID:
            for hm in HOME_MULT_GRID:
                for am in AWAY_MULT_GRID:
                    preds = predict_vectorized(feats, alpha, hm, am)
                    residuals = preds - actuals
                    results.append({
                        "alpha": alpha,
                        "home_mult": hm,
                        "away_mult": am,
                        "mse": float((residuals ** 2).mean()),
                        "mean_residual": float(residuals.mean()),
                    })
        results_df = pd.DataFrame(results)

        best = results_df.loc[results_df["mse"].idxmin()]
        print(f"\n=== Optimum ===")
        print(f"  alpha           = {best['alpha']:.2f}")
        print(f"  home_multiplier = {best['home_mult']:.2f}")
        print(f"  away_multiplier = {best['away_mult']:.2f}")
        print(f"  MSE             = {best['mse']:.4f}")
        print(f"  mean residual   = {best['mean_residual']:.4f}")

        # Marginal best at each alpha (over all home/away combos)
        print(f"\n=== Best MSE at each alpha (marginal over home_mult, away_mult) ===")
        idx = results_df.groupby("alpha")["mse"].idxmin()
        marginal_alpha = results_df.loc[idx, ["alpha", "home_mult", "away_mult", "mse", "mean_residual"]]
        print(marginal_alpha.to_string(index=False))

        # Slice through optimum: vary alpha, hold mults at best
        print(f"\n=== MSE vs alpha at best home_mult={best['home_mult']:.2f}, "
              f"away_mult={best['away_mult']:.2f} ===")
        slice_df = results_df[
            (results_df["home_mult"] == best["home_mult"]) &
            (results_df["away_mult"] == best["away_mult"])
        ][["alpha", "mse", "mean_residual"]].sort_values("alpha")
        print(slice_df.to_string(index=False))

        print(f"\n=== Top 10 grid points by MSE ===")
        print(results_df.nsmallest(10, "mse").to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    main()