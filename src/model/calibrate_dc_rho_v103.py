"""
V1.03 modeling — B2a: Calibrate Dixon-Coles rho parameter via MLE.

WHAT THIS DOES
    For all played PL matches in 2024-25 + 2025-26 (750 total):
      1. Compute the B1.2 prediction (xg_home, xg_away).
      2. Build the independent-Poisson 8x8 score grid (same logic as
         the MD38 prediction script).
      3. Define the Dixon-Coles tau correction parametrized by rho:
            tau(0,0) = 1 - xg_home * xg_away * rho
            tau(0,1) = 1 + xg_home * rho
            tau(1,0) = 1 + xg_away * rho
            tau(1,1) = 1 - rho
            tau(i,j) = 1 for all other cells
      4. For a given rho, look up P(actual scoreline | rho) for each
         match and sum log-likelihoods.
      5. Optimize rho via scipy.optimize.minimize_scalar in [-0.2, 0.2].
      6. Report optimum + diagnostics + write to model_parameters_v103.

WHY THIS IS PATH Z (post-processor, not full DC re-fit)
    We do NOT re-estimate team attack/defense parameters. We hold B1.2's
    xG estimates fixed and calibrate ONLY rho. This is methodologically
    weaker than canonical Dixon-Coles (where rho is jointly estimated
    with team strengths via MLE) but is the lowest-risk forward step
    that improves on B1.2 before MD38 kickoff.

LEAKAGE CAVEAT
    The B1.2 xG values used here were computed from team_season_strength
    estimates that were themselves derived from these same matches. This
    is the same V1.03 leakage that's already documented and parked for
    V1.04. We accept it here for consistency with V1.03.

REFERENCES
    Dixon & Coles 1997, "Modelling Association Football Scores and
    Inefficiencies in the Football Betting Market":
        http://web.math.ku.dk/~rolf/teaching/thesis/DixonColes.pdf

HOW TO RUN
    From the repo root:
        uv run python src/model/calibrate_dc_rho_v103.py
"""

import sys
from pathlib import Path

import duckdb
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

# Make src.* importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.model.predict_xg_v103 import predict_xg  # noqa: E402

DB_PATH = Path("data/processed/worldcup.duckdb")
MAX_GOALS = 7
RHO_BOUNDS = (-0.2, 0.2)  # standard literature range


# ---------------------------------------------------------------------------
# Vectorized tau correction
# ---------------------------------------------------------------------------
def apply_tau_correction(grid: np.ndarray,
                          xg_home: float,
                          xg_away: float,
                          rho: float) -> np.ndarray:
    """
    Apply Dixon-Coles tau correction to a (MAX_GOALS+1, MAX_GOALS+1)
    independent-Poisson grid. Returns the renormalized corrected grid.

    Only the four low-score cells are modified:
        (0,0) (0,1) (1,0) (1,1)
    All other cells get tau=1 (unchanged).
    """
    corrected = grid.copy()
    corrected[0, 0] *= 1.0 - xg_home * xg_away * rho
    corrected[0, 1] *= 1.0 + xg_home * rho
    corrected[1, 0] *= 1.0 + xg_away * rho
    corrected[1, 1] *= 1.0 - rho

    # Renormalize. Note: for valid rho, corrected cells stay positive,
    # but we floor at tiny epsilon to be safe against pathological rho
    # values during optimizer exploration.
    corrected = np.maximum(corrected, 1e-15)
    corrected /= corrected.sum()
    return corrected


# ---------------------------------------------------------------------------
# Negative log-likelihood for a candidate rho across all matches
# ---------------------------------------------------------------------------
def make_neg_log_likelihood(match_data):
    """
    Build a closure that takes rho and returns negative log-likelihood
    across all matches.

    match_data: list of dicts, one per match, each containing:
        xg_home, xg_away, poisson_grid, actual_home_goals, actual_away_goals
    """
    def neg_log_likelihood(rho: float) -> float:
        total_log_lik = 0.0
        for m in match_data:
            corrected = apply_tau_correction(
                m["poisson_grid"], m["xg_home"], m["xg_away"], rho
            )
            p_actual = corrected[m["actual_home_goals"],
                                  m["actual_away_goals"]]
            # log of tiny epsilon-floored prob is fine
            total_log_lik += np.log(p_actual)
        return -total_log_lik
    return neg_log_likelihood


# ---------------------------------------------------------------------------
# Build the Poisson grid for one fixture (same logic as MD38 runner)
# ---------------------------------------------------------------------------
def build_poisson_grid(xg_home: float, xg_away: float) -> np.ndarray:
    ks = np.arange(MAX_GOALS + 1)
    p_home = poisson.pmf(ks, mu=xg_home)
    p_away = poisson.pmf(ks, mu=xg_away)
    raw = np.outer(p_home, p_away)
    return raw / raw.sum()  # renormalize after truncation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Fetch all played matches (home-side rows give us both teams
        # and both goal counts in one row).
        print("Fetching played matches from team_match_stats...")
        matches = con.execute("""
            SELECT
                game_id,
                team AS home_team,
                opponent AS away_team,
                season,
                goals AS home_goals,
                opponent_goals AS away_goals
            FROM team_match_stats
            WHERE side = 'home'
            ORDER BY season, game_id
        """).fetchall()
        print(f"  Found {len(matches)} played matches.")

        # Goal-cap sanity check (we verified this is empty interactively,
        # but defensive in code).
        out_of_cap = [m for m in matches
                      if m[4] > MAX_GOALS or m[5] > MAX_GOALS]
        if out_of_cap:
            raise SystemExit(
                f"Found {len(out_of_cap)} matches with goals > "
                f"{MAX_GOALS} either side; widen MAX_GOALS or drop them. "
                f"First: {out_of_cap[0]}"
            )

        # 2. Pre-compute B1.2 predictions + Poisson grids for all matches.
        # This is the expensive step — done ONCE here, not per-rho-candidate.
        print(f"\nPre-computing B1.2 predictions + Poisson grids for "
              f"{len(matches)} matches...")
        match_data = []
        for i, (game_id, home, away, season, hg, ag) in enumerate(matches):
            if (i + 1) % 100 == 0:
                print(f"  {i+1}/{len(matches)}...")
            pred = predict_xg(con, home, away, season)
            grid = build_poisson_grid(pred.xg_home, pred.xg_away)
            match_data.append({
                "game_id": game_id,
                "xg_home": pred.xg_home,
                "xg_away": pred.xg_away,
                "poisson_grid": grid,
                "actual_home_goals": int(hg),
                "actual_away_goals": int(ag),
            })
        print(f"  Done. {len(match_data)} matches ready for optimization.")

        # 3. Baseline log-likelihood at rho=0 (independent Poisson).
        nll = make_neg_log_likelihood(match_data)
        ll_baseline = -nll(0.0)
        print(f"\nBaseline log-likelihood at rho=0 (indep Poisson): "
              f"{ll_baseline:.4f}")

        # 4. Optimize rho.
        print(f"\nOptimizing rho in {RHO_BOUNDS} via bounded minimize_scalar...")
        result = minimize_scalar(
            nll,
            bounds=RHO_BOUNDS,
            method="bounded",
            options={"xatol": 1e-6},
        )
        if not result.success:
            raise SystemExit(f"Optimizer failed: {result.message}")

        rho_opt = float(result.x)
        ll_opt = -float(result.fun)
        ll_improvement = ll_opt - ll_baseline
        avg_ll_improvement_per_match = ll_improvement / len(match_data)

        print(f"\n{'='*60}")
        print(f"OPTIMIZATION RESULT")
        print(f"{'='*60}")
        print(f"Optimal rho:              {rho_opt:+.6f}")
        print(f"Log-likelihood at opt:    {ll_opt:.4f}")
        print(f"Log-likelihood at rho=0:  {ll_baseline:.4f}")
        print(f"Improvement (total):      {ll_improvement:+.4f}")
        print(f"Improvement (per match):  {avg_ll_improvement_per_match:+.6f}")
        print(f"Converged:                {result.success}")
        print(f"Function evaluations:     {result.nfev}")

        # Sanity check: literature reports rho ~ -0.066 (Dixon & Coles 1997).
        # Modern PL data varies but typically -0.15 to -0.02.
        if rho_opt > 0:
            print(f"\nWARNING: positive rho is unusual for PL data. "
                  f"Literature reports negative values "
                  f"(more low-score draws than indep Poisson predicts). "
                  f"Sanity-check before using.")
        elif rho_opt < -0.15:
            print(f"\nNOTE: rho more negative than typical literature range. "
                  f"Worth checking the per-cell impact in B2c.")

        # 5. Create model_parameters_v103 table if needed; write rho row.
        # Table schema is generic so it can hold future params (e.g.
        # time-decay xi if we ever add it).
        print(f"\nWriting rho to model_parameters_v103...")
        con.execute("""
            CREATE TABLE IF NOT EXISTS model_parameters_v103 (
                parameter_name   VARCHAR     NOT NULL,
                model_version    VARCHAR     NOT NULL,
                value            DOUBLE      NOT NULL,
                n_matches_used   INTEGER     NOT NULL,
                log_likelihood   DOUBLE      NOT NULL,
                ll_vs_baseline   DOUBLE      NOT NULL,
                calibrated_at    TIMESTAMP   NOT NULL
                                     DEFAULT CURRENT_TIMESTAMP,
                notes            VARCHAR,
                PRIMARY KEY (parameter_name, model_version)
            )
        """)

        # Upsert: delete prior row for this (param, version), insert new.
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                """
                DELETE FROM model_parameters_v103
                WHERE parameter_name = ? AND model_version = ?
                """,
                ["dc_rho", "B2_v103_dc_post_hoc"],
            )
            con.execute(
                """
                INSERT INTO model_parameters_v103 (
                    parameter_name, model_version, value,
                    n_matches_used, log_likelihood, ll_vs_baseline,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    "dc_rho",
                    "B2_v103_dc_post_hoc",
                    rho_opt,
                    len(match_data),
                    ll_opt,
                    ll_improvement,
                    "MLE on B1.2 xG inputs, 2024-25 + 2025-26 played matches. "
                    "Path Z: post-processor on B1.2, not full DC re-fit.",
                ],
            )
            con.execute("COMMIT")
            print(f"  Wrote (parameter='dc_rho', model_version="
                  f"'B2_v103_dc_post_hoc', value={rho_opt:+.6f}).")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


if __name__ == "__main__":
    main()