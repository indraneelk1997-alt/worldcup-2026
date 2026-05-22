"""
V1.03 B1.2: Predict team xG from team-level strength features.

Formula (multiplicative, Pythagorean / SPI structure):

    xG_team = (own_avg_xg_for * opp_avg_xg_allowed / league_avg_xg)
            * side_multiplier

Where:
    own_avg_xg_for      = predicting team's avg xG scored per match (season)
    opp_avg_xg_allowed  = opponent's avg xG conceded per match (season)
    league_avg_xg       = per-season league average xG per team-match
    side_multiplier     = home_multiplier when predicting team is home,
                          else away_multiplier

CALIBRATED PARAMETER DEFAULTS (from calibrate_b12_v103.py joint MSE grid search
on 1500 EPL team-matches across 2024-2025 + 2025-2026):
    home_multiplier = 1.05
    away_multiplier = 0.90

PRESSING TERM: An opponent PPDA multiplier was included in the B1.2 design and
calibrated jointly with the side multipliers. Optimal α landed at 0.00,
meaning the term contributed nothing once opp_avg_xg_allowed was in the model.
PPDA and opp_xg_allowed correlate at r=0.53 across team-seasons; the
multiplicative form absorbs the pressing signal into the defensive term.
Diagnosed in analysis/investigations/investigate_residuals_b12.py — PPDA
residual spread fell from 0.38 (V1.03) to 0.026 (B1.2). The pressing term
was therefore removed from the formula.

Pure function — does not write to DB. Read-only DuckDB access. Caller opens
the connection and passes it in.

Leakage caveat: team averages in team_season_strength_v103 are computed from
the entire season, including the match being predicted. Documented in
V1.03 methodology; not corrected in B1.2 first pass.
"""

from dataclasses import dataclass
import duckdb
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "worldcup.duckdb"

DEFAULT_HOME_MULTIPLIER = 1.05
DEFAULT_AWAY_MULTIPLIER = 0.90


class TeamSeasonNotFoundError(Exception):
    """Raised when a (team, season) combo is missing from team_season_strength_v103."""


class LeagueAverageNotFoundError(Exception):
    """Raised when a season is missing from league_averages_v103."""


@dataclass(frozen=True)
class TeamStrength:
    team: str
    season: str
    avg_xg_for: float
    avg_xg_allowed: float


@dataclass(frozen=True)
class LeagueAverages:
    season: str
    league_avg_xg: float


@dataclass(frozen=True)
class XgPrediction:
    home_team: str
    away_team: str
    season: str
    xg_home: float
    xg_away: float
    # diagnostics — exposed so the prediction loader can persist them
    home_attack_x_opp_defense: float
    home_side_multiplier: float
    away_attack_x_opp_defense: float
    away_side_multiplier: float


def get_team_strength(
    con: duckdb.DuckDBPyConnection, team: str, season: str
) -> TeamStrength:
    row = con.execute(
        """
        SELECT team, season, avg_xg_for, avg_xg_allowed
        FROM team_season_strength_v103
        WHERE team = ? AND season = ?
        """,
        [team, season],
    ).fetchone()
    if row is None:
        raise TeamSeasonNotFoundError(
            f"No row in team_season_strength_v103 for team={team!r}, season={season!r}"
        )
    return TeamStrength(*row)


def get_league_averages(
    con: duckdb.DuckDBPyConnection, season: str
) -> LeagueAverages:
    row = con.execute(
        """
        SELECT season, league_avg_xg
        FROM league_averages_v103
        WHERE season = ?
        """,
        [season],
    ).fetchone()
    if row is None:
        raise LeagueAverageNotFoundError(
            f"No row in league_averages_v103 for season={season!r}"
        )
    return LeagueAverages(*row)


def predict_xg(
    con: duckdb.DuckDBPyConnection,
    home_team: str,
    away_team: str,
    season: str,
    home_multiplier: float = DEFAULT_HOME_MULTIPLIER,
    away_multiplier: float = DEFAULT_AWAY_MULTIPLIER,
) -> XgPrediction:
    """Predict (xG_home, xG_away) for a single matchup using B1.2 formula."""
    home = get_team_strength(con, home_team, season)
    away = get_team_strength(con, away_team, season)
    league = get_league_averages(con, season)

    home_attack_x_opp_defense = (
        home.avg_xg_for * away.avg_xg_allowed / league.league_avg_xg
    )
    xg_home = home_attack_x_opp_defense * home_multiplier

    away_attack_x_opp_defense = (
        away.avg_xg_for * home.avg_xg_allowed / league.league_avg_xg
    )
    xg_away = away_attack_x_opp_defense * away_multiplier

    return XgPrediction(
        home_team=home_team,
        away_team=away_team,
        season=season,
        xg_home=xg_home,
        xg_away=xg_away,
        home_attack_x_opp_defense=home_attack_x_opp_defense,
        home_side_multiplier=home_multiplier,
        away_attack_x_opp_defense=away_attack_x_opp_defense,
        away_side_multiplier=away_multiplier,
    )


def _smoke_test() -> None:
    """Verify the simplified formula still produces sensible numbers for
    known matchups."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # Strong-vs-strong — Arsenal-Liverpool 2024-2025 (actual 1.09 / 0.48)
        pred = predict_xg(con, "Arsenal", "Liverpool", "2024-2025")
        print(f"Arsenal (H) vs Liverpool (A), 2024-2025:")
        print(f"  predicted: home={pred.xg_home:.3f}, away={pred.xg_away:.3f}")

        # Strong vs weak — Man City vs Southampton 2024-2025
        pred = predict_xg(con, "Manchester City", "Southampton", "2024-2025")
        print(f"\nMan City (H) vs Southampton (A), 2024-2025:")
        print(f"  predicted: home={pred.xg_home:.3f}, away={pred.xg_away:.3f}")

        # Aston Villa vs Man City — the S9 anomaly
        pred = predict_xg(con, "Aston Villa", "Manchester City", "2024-2025")
        print(f"\nAston Villa (H) vs Man City (A), 2024-2025:")
        print(f"  predicted: home={pred.xg_home:.3f}, away={pred.xg_away:.3f}")

    finally:
        con.close()


if __name__ == "__main__":
    _smoke_test()