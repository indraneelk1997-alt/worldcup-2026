"""
V1.02 Poisson match simulator — engine.

WHAT THIS DOES
    Pure-function engine for V1.02 match predictions. Two callable
    flavors of team strength (weighted vs unweighted), shared math for
    xG / Poisson simulation / prediction logging.

    The runner (src/simulate/run_md38_predictions.py) handles scenario
    creation, fixture iteration, and orchestrates calls to this engine.

CHANGES FROM V1.01
    - Reads lineups via scenario_id (not fixture_id directly).
      The V1.02 schema rebound fixture_lineups -> scenario in S6.
    - Uses BLENDED SHRUNK rating instead of raw rating_per_90.
      blended = 0.75 * shrunk_form + 0.25 * shrunk_consistency
    - Adds HOME_BONUS to xG calculation (+0.15 home, -0.15 away).
      Empirically validated in football analytics literature.
    - TWO strength variants:
        unweighted: SUM(blended_rating)
        weighted:   SUM(blended_rating * OFFENSIVE_WEIGHT[position_code])
      Run both, compare, see if 18-code position weights help or hurt.
    - Writes via scenario_id on predictions (S6 part 2 schema change).

CALIBRATION (S9 lock; tunable later)
    BASE_GOALS  = 1.4    # carried from V1.01 — kept for comparability
    HOME_BONUS  = 0.15   # net home advantage 0.30 goals/match
    K           = 1.0    # carried from V1.01
    N_SIMS      = 10_000 # carried from V1.01
    RNG_SEED    = 42     # carried for reproducibility

OFFENSIVE_WEIGHT (18 position codes)
    Class anchors derived from data (S9): GK 0.01, DEF 0.29, MID 0.54,
    FWD 1.00 — ratios of class-mean rating_per_90 to FWD-mean. Within-
    class distribution is football-intuition tuned (CB < FB < WB,
    DM < CM < CAM, ST ≈ wide forwards).
"""

import duckdb
import numpy as np
from scipy.stats import poisson
from collections import Counter
from datetime import datetime
from pathlib import Path


# --- calibration (S9) ------------------------------------------------------
BASE_GOALS    = 1.4
HOME_BONUS    = 0.15
K             = 1.0
N_SIMULATIONS = 10_000
RNG_SEED      = 42

# Blend weights, consistent with select_best_xi.py.
FORM_WEIGHT = 0.75  # 0.75 * shrunk_form + 0.25 * shrunk_consistency


# --- 18-code offensive weights (S9, data-anchored at class level) ----------
OFFENSIVE_WEIGHT = {
    # GK — no offensive contribution; locked-in by minutes anyway
    "GK": 0.00,

    # DEF — pure CBs low, fullbacks moderate, wing-backs higher
    "CB":  0.20, "RCB": 0.20, "LCB": 0.20,
    "RB":  0.30, "LB":  0.30,
    "RWB": 0.45, "LWB": 0.45,

    # MID — defensive screen low, box-to-box moderate, wide and #10 higher
    "DM":  0.30,
    "RCM": 0.45, "CM":  0.45, "LCM": 0.45,
    "RM":  0.60, "LM":  0.60,
    "CAM": 0.75,

    # FWD — wide forwards slightly higher than central striker (more xA share)
    "RW":  1.10, "LW":  1.10, "ST":  1.00,
}


# ===========================================================================
# Strength calculation — TWO variants
# ===========================================================================
def get_team_strength_unweighted(con, scenario_id, side, season):
    """
    SUM of blended shrunk rating across the 10 outfielders + GK.
    GK contributes ~0 anyway (shrunk_form near zero), so no special-case.
    """
    result = con.execute("""
        SELECT SUM(? * pss.shrunk_form + ? * pss.shrunk_consistency)
        FROM fixture_lineups fl
        JOIN scenario_teams st
          ON st.scenario_id = fl.scenario_id
         AND st.side = fl.side
        JOIN player_season_stats pss
          ON pss.player_id = fl.player_id
         AND pss.season = ?
         AND pss.team = st.team
        WHERE fl.scenario_id = ?
          AND fl.side = ?
    """, [FORM_WEIGHT, 1 - FORM_WEIGHT, season, scenario_id, side]).fetchone()
    return float(result[0]) if result[0] is not None else 0.0


def get_team_strength_weighted(con, scenario_id, side, season):
    """
    SUM of blended shrunk rating × OFFENSIVE_WEIGHT[position_code] across XI.
    Uses fixture_lineups -> formation_slots -> positions to get position_code
    per slot, then applies the 18-code weight.
    """
    # Need to join via slot_no to formation_slots to find each player's
    # position_code, then weight their blended rating accordingly.
    rows = con.execute("""
        SELECT
            fl.player_id,
            fs.position_code,
            (? * pss.shrunk_form + ? * pss.shrunk_consistency) AS blended
        FROM fixture_lineups fl
        JOIN scenario_teams st
          ON st.scenario_id = fl.scenario_id
         AND st.side = fl.side
        JOIN formation_slots fs
          ON fs.formation = st.formation
         AND fs.slot_no = fl.slot_no
        JOIN player_season_stats pss
          ON pss.player_id = fl.player_id
         AND pss.season = ?
         AND pss.team = st.team
        WHERE fl.scenario_id = ?
          AND fl.side = ?
    """, [FORM_WEIGHT, 1 - FORM_WEIGHT, season, scenario_id, side]).fetchall()

    total = 0.0
    for _, position_code, blended in rows:
        weight = OFFENSIVE_WEIGHT.get(position_code)
        if weight is None:
            raise ValueError(
                f"Unknown position_code '{position_code}' in fixture lineup "
                f"(scenario {scenario_id} {side}). Update OFFENSIVE_WEIGHT."
            )
        total += blended * weight
    return total


# ===========================================================================
# xG + Poisson sim (shared between variants)
# ===========================================================================
def expected_goals(strength_home, strength_away):
    """
    Linear-differential xG with home advantage.
    HOME_BONUS gives the home side +0.30 net goals/match advantage (well-
    documented in football analytics; e.g. Anderson & Sally 'The Numbers Game').
    """
    xg_home = max(0.0, BASE_GOALS + HOME_BONUS +
                  K * (strength_home - strength_away))
    xg_away = max(0.0, BASE_GOALS - HOME_BONUS +
                  K * (strength_away - strength_home))
    return xg_home, xg_away


def simulate(xg_home, xg_away, n=N_SIMULATIONS, seed=RNG_SEED):
    """Sample n match outcomes from independent Poissons."""
    rng = np.random.default_rng(seed)
    home_goals = rng.poisson(xg_home, size=n)
    away_goals = rng.poisson(xg_away, size=n)
    return home_goals, away_goals


def summarize_to_dict(home_goals, away_goals):
    """Return a dict of summary stats — used both for printing and writing."""
    n = len(home_goals)
    pairs = list(zip(home_goals.tolist(), away_goals.tolist()))
    (mh, ma), _ = Counter(pairs).most_common(1)[0]
    return {
        "n_simulations": n,
        "p_home_win":    float((home_goals > away_goals).mean()),
        "p_draw":        float((home_goals == away_goals).mean()),
        "p_away_win":    float((home_goals < away_goals).mean()),
        "avg_home_goals": float(home_goals.mean()),
        "avg_away_goals": float(away_goals.mean()),
        "modal_scoreline": f"{mh}-{ma}",
    }


# ===========================================================================
# Prediction write (V1.02 schema: scenario_id replaces fixture_id)
# ===========================================================================
def write_prediction(con, scenario_id, model_version,
                     strength_home, strength_away,
                     xg_home, xg_away,
                     summary, rng_seed=RNG_SEED):
    """
    Insert one row into predictions. V1.02 schema uses scenario_id, not
    fixture_id (per the S6 part-2 refactor).
    """
    run_ts = datetime.now()
    # Unique prediction_id: scenario + version + timestamp.
    prediction_id = (
        f"scn{scenario_id}_{model_version}_"
        f"{run_ts.strftime('%Y%m%d_%H%M%S_%f')}"
    )

    con.execute("""
        INSERT INTO predictions (
            prediction_id, scenario_id, model_version, run_timestamp,
            n_simulations, rng_seed, base_goals, k_param,
            home_strength, away_strength, xg_home, xg_away,
            p_home_win, p_draw, p_away_win,
            avg_home_goals, avg_away_goals, modal_scoreline
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        prediction_id, scenario_id, model_version, run_ts,
        summary["n_simulations"], rng_seed, BASE_GOALS, K,
        strength_home, strength_away, xg_home, xg_away,
        summary["p_home_win"], summary["p_draw"], summary["p_away_win"],
        summary["avg_home_goals"], summary["avg_away_goals"],
        summary["modal_scoreline"],
    ])
    return prediction_id


# ===========================================================================
# Convenience: run both variants for one scenario
# ===========================================================================
def run_both_variants(con, scenario_id, season, label_for_log=""):
    """
    For one scenario, compute strengths + xG + sim + write predictions
    for BOTH the unweighted and weighted variants. Returns a dict with
    both results so the runner can print a comparison.
    """
    out = {}
    for variant_name, strength_fn in [
        ("unweighted", get_team_strength_unweighted),
        ("weighted",   get_team_strength_weighted),
    ]:
        s_home = strength_fn(con, scenario_id, "home", season)
        s_away = strength_fn(con, scenario_id, "away", season)
        xg_h, xg_a = expected_goals(s_home, s_away)
        h_goals, a_goals = simulate(xg_h, xg_a)
        summ = summarize_to_dict(h_goals, a_goals)
        pred_id = write_prediction(
            con, scenario_id, f"v1.02_{variant_name}",
            s_home, s_away, xg_h, xg_a, summ,
        )
        out[variant_name] = {
            "strength_home": s_home,
            "strength_away": s_away,
            "xg_home": xg_h,
            "xg_away": xg_a,
            "summary": summ,
            "prediction_id": pred_id,
        }
    return out