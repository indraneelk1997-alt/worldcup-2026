"""
B1.2 residual diagnosis — multiplicative xG model with calibrated parameters.

Frozen exploratory script. Mirrors the structure of
investigate_residuals_v103.py so the two can be compared side-by-side.

Question: with α=0.0, home_mult=1.05, away_mult=0.90 (optimized in
calibrate_b12_v103.py), does residual structure remain in any of the
moderators that V1.03 had problems with — especially opponent PPDA, where
calibration said α=0 but the V1.03 script showed clear quintile spread?

Decision rule for PPDA:
  - If quintile spread > 0.2 xG in B1.2 residuals → pressing term is real
    but mis-specified; redesign before accepting α=0.
  - If quintile spread < 0.2 xG → PPDA's signal was absorbed by
    opp_avg_xg_allowed in the multiplicative form. Accept α=0; drop the
    pressing term from the formula.

Calibration values used here:
  ALPHA = 0.00         (pressing exponent — null after calibration)
  HOME_MULT = 1.05
  AWAY_MULT = 0.90

These are from the joint grid search on the same 1500 team-matches; same
leakage caveat as V1.03 (team averages include the match being predicted).
"""

import duckdb
import pandas as pd
from pathlib import Path
import sys

# Path hack so this script in analysis/investigations/ can import from src/model/
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "model"))

from predict_xg_v103 import DB_PATH  # noqa: E402


ALPHA = 0.00
HOME_MULT = 1.05
AWAY_MULT = 0.90


def load_feature_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Same join used in calibrate_b12_v103.py. Each row = one team-match
    with everything needed for prediction + diagnostic slicing."""
    df = con.execute(
        """
        SELECT
            tms.game_id,
            tms.team,
            tms.opponent,
            tms.season,
            tms.side,
            tms.xg                  AS actual_xg,
            own.avg_xg_for          AS own_avg_xg_for,
            own.avg_ppda_pressing   AS own_avg_ppda_pressing,
            opp.avg_xg_for          AS opp_avg_xg_for,
            opp.avg_xg_allowed      AS opp_avg_xg_allowed,
            opp.avg_ppda_pressing   AS opp_avg_ppda_pressing,
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


def add_predictions(feats: pd.DataFrame) -> pd.DataFrame:
    """Add predicted_xg and residual columns to the feature table."""
    attack_x_defense = (
        feats["own_avg_xg_for"] * feats["opp_avg_xg_allowed"] / feats["league_avg_xg"]
    )
    pressing_mult = (
        feats["opp_avg_ppda_pressing"] / feats["league_avg_ppda"]
    ) ** ALPHA
    side_mult = feats["side"].map({"home": HOME_MULT, "away": AWAY_MULT})
    feats["predicted_xg"] = attack_x_defense * pressing_mult * side_mult
    feats["residual"] = feats["predicted_xg"] - feats["actual_xg"]
    return feats


def quintile_summary(df: pd.DataFrame, column: str, label: str) -> None:
    """Bucket df by quintile of `column`, print residual stats per bucket."""
    df = df.copy()
    df["bucket"] = pd.qcut(df[column], 5, labels=False, duplicates="drop")
    grouped = df.groupby("bucket").agg(
        n=("residual", "size"),
        min_col=(column, "min"),
        max_col=(column, "max"),
        mean_res=("residual", "mean"),
        sd_res=("residual", "std"),
        median_res=("residual", "median"),
    )
    print(f"\n=== Residual by {label} quintile ===")
    print(f"  bucket   range                 n   mean res   sd res   median")
    for b, row in grouped.iterrows():
        rng = f"{row['min_col']:.3f}-{row['max_col']:.3f}"
        print(
            f"  {int(b):<8} {rng:<20} {int(row['n']):>4}     "
            f"{row['mean_res']:+.3f}    {row['sd_res']:.3f}   {row['median_res']:+.3f}"
        )
    spread = grouped["mean_res"].max() - grouped["mean_res"].min()
    print(f"  --> mean-residual spread across quintiles: {spread:.3f}")


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        feats = load_feature_table(con)
        feats = add_predictions(feats)

        print(f"=== STEP 1: B1.2 predictions ===")
        print(f"  alpha={ALPHA}, home_mult={HOME_MULT}, away_mult={AWAY_MULT}")
        print(f"  n team-matches = {len(feats)}")
        print()

        print(f"=== STEP 2: overall residual stats ===")
        r = feats["residual"]
        print(f"  mean residual    = {r.mean():+.3f}")
        print(f"  sd residual      = {r.std():.3f}")
        print(f"  MSE              = {(r ** 2).mean():.4f}")
        print(f"  mean predicted   = {feats['predicted_xg'].mean():.3f}")
        print(f"  mean actual      = {feats['actual_xg'].mean():.3f}")
        print(f"  Pearson r (pred, actual) = "
              f"{feats['predicted_xg'].corr(feats['actual_xg']):.3f}  "
              f"(note: leakage in season averages; treat as upper bound)")

        # --- the key diagnostic: PPDA quintile spread ---
        quintile_summary(feats, "opp_avg_ppda_pressing", "opponent_avg_PPDA")

        # --- sanity checks for the other moderators from S11 ---
        quintile_summary(feats, "opp_avg_xg_allowed", "opponent_avg_xg_allowed")
        quintile_summary(feats, "opp_avg_xg_for", "opponent_avg_xg_for (their attack)")

        # --- saturation check: does residual depend on predicted_xg level? ---
        quintile_summary(feats, "predicted_xg", "predicted_xg")

        # --- home vs away ---
        print(f"\n=== STEP 5: home vs away residual split ===")
        for side, sub in feats.groupby("side"):
            print(f"  {side:<5} n={len(sub):>4} mean_residual={sub['residual'].mean():+.3f}")

        # --- extreme residuals ---
        print(f"\n=== STEP 6: extreme residuals ===")
        cols = ["team", "opponent", "season", "predicted_xg", "actual_xg", "residual"]
        print(f"\nBottom 8 (most negative residuals — model UNDERPREDICTED: predicted << actual):")
        print(feats.nsmallest(8, "residual")[cols].to_string(index=False))
        print(f"\nTop 8 (most positive residuals — model OVERPREDICTED: predicted >> actual):")
        print(feats.nlargest(8, "residual")[cols].to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    main()