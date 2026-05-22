"""
V1.03 B1.2: Compute per-team-per-season strength features and global league
averages from team_match_stats.

Source: team_match_stats (1500 team-match rows, long format).

Outputs two tables:
  - team_season_strength_v103: (team, season) -> avg_xg_for, avg_xg_allowed,
    avg_ppda_pressing, n_matches
  - league_averages_v103: (season) -> league_avg_xg, league_avg_ppda,
    n_team_matches  (one row per season, plus a 'GLOBAL' row across all seasons)

Semantics note: avg_ppda_pressing is the team's OWN pressing intensity
(team_match_stats.ppda), i.e. how aggressively this team presses opponents.
Used downstream as the opponent's pressing multiplier when predicting
xG against this team.

Idempotent: CREATE IF NOT EXISTS + INSERT OR IGNORE. Re-run safe; will not
update existing rows. To refresh, drop the rows manually.
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "worldcup.duckdb"


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS team_season_strength_v103 (
            team VARCHAR NOT NULL,
            season VARCHAR NOT NULL,
            n_matches INTEGER NOT NULL,
            avg_xg_for DOUBLE NOT NULL,
            avg_xg_allowed DOUBLE NOT NULL,
            avg_ppda_pressing DOUBLE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (team, season)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS league_averages_v103 (
            season VARCHAR PRIMARY KEY,
            league_avg_xg DOUBLE NOT NULL,
            league_avg_ppda DOUBLE NOT NULL,
            n_team_matches INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def load_team_season_strength(con: duckdb.DuckDBPyConnection) -> int:
    """Insert one row per (team, season). Returns rows inserted."""
    before = con.execute("SELECT COUNT(*) FROM team_season_strength_v103").fetchone()[0]
    con.execute("""
        INSERT OR IGNORE INTO team_season_strength_v103
            (team, season, n_matches, avg_xg_for, avg_xg_allowed, avg_ppda_pressing)
        SELECT
            team,
            season,
            COUNT(*) AS n_matches,
            AVG(xg) AS avg_xg_for,
            AVG(opponent_xg) AS avg_xg_allowed,
            AVG(ppda) AS avg_ppda_pressing
        FROM team_match_stats
        GROUP BY team, season
    """)
    after = con.execute("SELECT COUNT(*) FROM team_season_strength_v103").fetchone()[0]
    return after - before


def load_league_averages(con: duckdb.DuckDBPyConnection) -> int:
    """Insert one row per season + one GLOBAL row. Returns rows inserted."""
    before = con.execute("SELECT COUNT(*) FROM league_averages_v103").fetchone()[0]
    # Per-season averages
    con.execute("""
        INSERT OR IGNORE INTO league_averages_v103
            (season, league_avg_xg, league_avg_ppda, n_team_matches)
        SELECT
            season,
            AVG(xg) AS league_avg_xg,
            AVG(ppda) AS league_avg_ppda,
            COUNT(*) AS n_team_matches
        FROM team_match_stats
        GROUP BY season
    """)
    # Global average across all seasons (using 'GLOBAL' as the season key)
    con.execute("""
        INSERT OR IGNORE INTO league_averages_v103
            (season, league_avg_xg, league_avg_ppda, n_team_matches)
        SELECT
            'GLOBAL' AS season,
            AVG(xg) AS league_avg_xg,
            AVG(ppda) AS league_avg_ppda,
            COUNT(*) AS n_team_matches
        FROM team_match_stats
    """)
    after = con.execute("SELECT COUNT(*) FROM league_averages_v103").fetchone()[0]
    return after - before


def main() -> None:
    print(f"Connecting to {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))

    create_tables(con)

    n_team_rows = load_team_season_strength(con)
    n_league_rows = load_league_averages(con)

    print(f"\nteam_season_strength_v103: inserted {n_team_rows} new rows")
    print(f"league_averages_v103:     inserted {n_league_rows} new rows")

    print("\n=== team_season_strength_v103 ===")
    df = con.execute("""
        SELECT team, season, n_matches,
               ROUND(avg_xg_for, 3) AS avg_xg_for,
               ROUND(avg_xg_allowed, 3) AS avg_xg_allowed,
               ROUND(avg_ppda_pressing, 2) AS avg_ppda_pressing
        FROM team_season_strength_v103
        ORDER BY season, team
    """).df()
    print(df.to_string(index=False))

    print("\n=== league_averages_v103 ===")
    df = con.execute("""
        SELECT season,
               ROUND(league_avg_xg, 3) AS league_avg_xg,
               ROUND(league_avg_ppda, 2) AS league_avg_ppda,
               n_team_matches
        FROM league_averages_v103
        ORDER BY season
    """).df()
    print(df.to_string(index=False))

    con.close()


if __name__ == "__main__":
    main()