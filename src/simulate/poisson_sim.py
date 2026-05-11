"""
V1.01 Poisson match simulator.
Reads a fixture's lineups from DuckDB, computes team strengths,
maps to expected goals, samples N match outcomes from Poisson.
"""
import duckdb
import numpy as np
from scipy.stats import poisson
from pathlib import Path
from collections import Counter
from datetime import datetime

DB_PATH = Path("data/processed/worldcup.duckdb")

# Calibration parameters (V1.01 starting values)
BASE_GOALS = 1.4
K = 1.0
N_SIMULATIONS = 10_000
RNG_SEED = 42  # reproducibility


def get_team_strength(con, fixture_id: str, team: str, season: str) -> float:
    """Sum rating_per_90 across the starting XI for a team in a fixture."""
    result = con.execute("""
        SELECT SUM(s.rating_per_90)
        FROM fixture_lineups fl
        JOIN player_season_stats s
          ON s.player_id = fl.player_id
         AND s.season = ?
         AND s.team = fl.team
        WHERE fl.fixture_id = ?
          AND fl.team = ?
          AND fl.is_starter = TRUE
    """, [season, fixture_id, team]).fetchone()
    return result[0]


def expected_goals(home_strength: float, away_strength: float):
    """Linear-differential model from team strengths to xG per side."""
    xg_home = max(0.0, BASE_GOALS + K * (home_strength - away_strength))
    xg_away = max(0.0, BASE_GOALS + K * (away_strength - home_strength))
    return xg_home, xg_away


def simulate(xg_home: float, xg_away: float, n: int, seed: int):
    """Sample n match outcomes from independent Poissons."""
    rng = np.random.default_rng(seed)
    home_goals = rng.poisson(xg_home, size=n)
    away_goals = rng.poisson(xg_away, size=n)
    return home_goals, away_goals


def summarize(home_goals, away_goals, home_team: str, away_team: str):
    n = len(home_goals)
    home_wins = int((home_goals > away_goals).sum())
    draws     = int((home_goals == away_goals).sum())
    away_wins = int((home_goals < away_goals).sum())
    avg_home  = float(home_goals.mean())
    avg_away  = float(away_goals.mean())
    
    # Top 5 most likely scorelines
    pairs = list(zip(home_goals.tolist(), away_goals.tolist()))
    top_scores = Counter(pairs).most_common(5)
    
    print(f"\n=== {home_team} (home) vs {away_team} (away) ===")
    print(f"Simulations: {n:,}")
    print(f"\nWin probabilities:")
    print(f"  {home_team:12s} win: {home_wins/n:6.1%}")
    print(f"  Draw:            {draws/n:6.1%}")
    print(f"  {away_team:12s} win: {away_wins/n:6.1%}")
    print(f"\nAverage scoreline: {avg_home:.2f} - {avg_away:.2f}")
    print(f"Expected goal diff: {avg_home - avg_away:+.2f}")
    print(f"\nTop 5 most likely scorelines:")
    for (h, a), count in top_scores:
        print(f"  {h}-{a}: {count/n:5.1%}")

def write_prediction(con, fixture_id, model_version,
                     home_strength, away_strength,
                     xg_home, xg_away,
                     home_goals, away_goals,
                     n_simulations, rng_seed,
                     base_goals, k_param):
    """Insert a single prediction row summarizing this simulator run."""
    n = len(home_goals)
    p_home_win = float((home_goals > away_goals).mean())
    p_draw     = float((home_goals == away_goals).mean())
    p_away_win = float((home_goals < away_goals).mean())
    avg_home   = float(home_goals.mean())
    avg_away   = float(away_goals.mean())
    
    # Modal scoreline
    pairs = list(zip(home_goals.tolist(), away_goals.tolist()))
    (mh, ma), _ = Counter(pairs).most_common(1)[0]
    modal_scoreline = f"{mh}-{ma}"
    
    # Build a unique prediction_id: fixture + version + timestamp
    run_ts = datetime.now()
    prediction_id = f"{fixture_id}_{model_version}_{run_ts.strftime('%Y%m%d_%H%M%S')}"
    
    con.execute("""
        INSERT INTO predictions (
            prediction_id, fixture_id, model_version, run_timestamp,
            n_simulations, rng_seed, base_goals, k_param,
            home_strength, away_strength, xg_home, xg_away,
            p_home_win, p_draw, p_away_win,
            avg_home_goals, avg_away_goals, modal_scoreline
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        prediction_id, fixture_id, model_version, run_ts,
        n_simulations, rng_seed, base_goals, k_param,
        home_strength, away_strength, xg_home, xg_away,
        p_home_win, p_draw, p_away_win,
        avg_home, avg_away, modal_scoreline
    ])
    
    print(f"\n✓ Prediction written: {prediction_id}")

def main():
    fixture_id = "2024-25_ars_liv_trial"
    season = "2024-2025"
    
    con = duckdb.connect(str(DB_PATH))
    try:
        # Get fixture metadata
        fixture = con.execute(
            "SELECT home_team, away_team FROM fixtures WHERE fixture_id = ?",
            [fixture_id]
        ).fetchone()
        home_team, away_team = fixture
        
        # Get strengths
        home_strength = get_team_strength(con, fixture_id, home_team, season)
        away_strength = get_team_strength(con, fixture_id, away_team, season)
        print(f"{home_team} strength: {home_strength:.3f}")
        print(f"{away_team} strength: {away_strength:.3f}")
        
        # Compute xG
        xg_home, xg_away = expected_goals(home_strength, away_strength)
        print(f"xG {home_team}: {xg_home:.3f}")
        print(f"xG {away_team}: {xg_away:.3f}")
        
        # Simulate
        home_goals, away_goals = simulate(xg_home, xg_away, N_SIMULATIONS, RNG_SEED)
        summarize(home_goals, away_goals, home_team, away_team)
        # Persist prediction
        write_prediction(
            con,
            fixture_id=fixture_id,
            model_version="v1.01",
            home_strength=home_strength,
            away_strength=away_strength,
            xg_home=xg_home,
            xg_away=xg_away,
            home_goals=home_goals,
            away_goals=away_goals,
            n_simulations=N_SIMULATIONS,
            rng_seed=RNG_SEED,
            base_goals=BASE_GOALS,
            k_param=K,
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()