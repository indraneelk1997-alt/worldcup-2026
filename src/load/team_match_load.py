"""
V1.03 modeling — STEP 2: team_match_stats schema + loader.

WHAT THIS DOES
    Two operations in one file:
      1. Creates `team_match_stats` table (long format — one row per
         team-match, NOT per match).
      2. Pulls per-team-match data from Understat, transforms from the
         wide Understat format to our long format, and inserts.

LONG vs WIDE FORMAT (S10 decision)
    Understat returns wide: one row per match with home_xg, away_xg,
    home_ppda, away_ppda, etc. all on the same row.
    We store long: two rows per match (home + away), each from that
    team's perspective with `team_xg`, `opponent_xg`, etc.
    Trade: 2× row count (~750 -> ~1500), but every team-side query
    becomes a single WHERE on `team` instead of UNION ALL of two arms.
    Schema is symmetric with player_match_stats too — both are
    one-row-per-(entity, game).

KEY DEFENSIVE METRIC
    `opponent_xg` = the xG the opponent posted against this team.
    Modern xGA proxy (per StatsBomb's xG-against framework). Direct
    input for V1.03 team defensive strength calculations.

SEASON STRING NORMALIZATION
    Understat returns '2425'/'2526'; our DB uses '2024-2025'/'2025-2026'.

IDEMPOTENCY
    Schema: CREATE IF NOT EXISTS.
    Loader: wipes team_match_stats by season then re-inserts.

FK NOTE
    team_match_stats.game_id references games(game_id). Per-team-match
    data should be a STRICT SUBSET of game_ids in `games` (which was
    populated from per-PLAYER-match data in A1). If a team-match game_id
    doesn't exist in games, that's an integrity error — we raise.

HOW TO RUN
    From the repo root:
        uv run python src/load/team_match_load.py
"""

import duckdb
import soccerdata as sd
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

SEASON_MAP = {
    "2024-2025": "2425",
    "2025-2026": "2526",
}


def ensure_schema(con):
    """Create team_match_stats if it doesn't exist."""
    existing = {
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    if "team_match_stats" in existing:
        print("`team_match_stats` already exists.")
        return False

    print("Creating `team_match_stats` table...")
    con.execute("""
        CREATE TABLE team_match_stats (
            game_id                   INTEGER NOT NULL REFERENCES games(game_id),
            team                      VARCHAR NOT NULL,
            side                      VARCHAR NOT NULL CHECK (side IN ('home', 'away')),
            season                    VARCHAR NOT NULL,
            opponent                  VARCHAR NOT NULL,
            points                    INTEGER NOT NULL,
            expected_points           DOUBLE  NOT NULL,
            goals                     INTEGER NOT NULL,
            opponent_goals            INTEGER NOT NULL,
            xg                        DOUBLE  NOT NULL,
            opponent_xg               DOUBLE  NOT NULL,
            np_xg                     DOUBLE  NOT NULL,
            opponent_np_xg            DOUBLE  NOT NULL,
            np_xg_difference          DOUBLE  NOT NULL,
            ppda                      DOUBLE  NOT NULL,
            opponent_ppda             DOUBLE  NOT NULL,
            deep_completions          INTEGER NOT NULL,
            opponent_deep_completions INTEGER NOT NULL,
            PRIMARY KEY (game_id, team)
        )
    """)
    print("  Created.")
    return True


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # 1. Pull team-match data.
    print("Loading Understat team-match stats (uses local cache)...")
    us = sd.Understat(
        leagues="ENG-Premier League",
        seasons=list(SEASON_MAP.keys()),
    )
    df = us.read_team_match_stats().reset_index()
    print(f"  Loaded {len(df)} raw rows (wide format).")

    # 2. Normalize season.
    sd_to_db_season = {v: k for k, v in SEASON_MAP.items()}
    sd_to_db_season.update({db: db for db in SEASON_MAP})
    df["season_db"] = df["season"].astype(str).map(sd_to_db_season)
    if df["season_db"].isna().any():
        raise SystemExit(
            f"Unmapped seasons: "
            f"{df.loc[df['season_db'].isna(), 'season'].unique()}"
        )

    # 3. Connect + create schema + check prereqs.
    con = duckdb.connect(str(DB_PATH))
    try:
        ensure_schema(con)

        # Check games table exists and the game_ids we have are in it.
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if "games" not in existing:
            raise SystemExit(
                "`games` table missing. Run A1 first "
                "(src/load/player_match_schema.py + "
                "src/load/backfill_player_match.py)."
            )

        games_in_db = {
            r[0] for r in con.execute(
                "SELECT game_id FROM games"
            ).fetchall()
        }
        games_in_df = {int(g) for g in df["game_id"].unique()}
        missing = games_in_df - games_in_db
        if missing:
            raise SystemExit(
                f"FK violation: {len(missing)} game_ids in team-match "
                f"data not present in `games`. First few: "
                f"{sorted(missing)[:5]}. Re-run A1 backfill."
            )
        extra = games_in_db - games_in_df
        if extra:
            print(f"  Note: {len(extra)} game_ids in `games` have no "
                  f"team-match data (likely unplayed). That's fine.")

        # 4. Transform wide -> long. Each input row becomes 2 output rows.
        long_rows = []
        for r in df.itertuples(index=False):
            game_id = int(r.game_id)
            season_db = r.season_db
            # Home perspective
            long_rows.append((
                game_id, str(r.home_team), "home", season_db,
                str(r.away_team),
                int(r.home_points), float(r.home_expected_points),
                int(r.home_goals), int(r.away_goals),
                float(r.home_xg), float(r.away_xg),
                float(r.home_np_xg), float(r.away_np_xg),
                float(r.home_np_xg_difference),
                float(r.home_ppda), float(r.away_ppda),
                int(r.home_deep_completions),
                int(r.away_deep_completions),
            ))
            # Away perspective (np_xg_difference flips sign)
            long_rows.append((
                game_id, str(r.away_team), "away", season_db,
                str(r.home_team),
                int(r.away_points), float(r.away_expected_points),
                int(r.away_goals), int(r.home_goals),
                float(r.away_xg), float(r.home_xg),
                float(r.away_np_xg), float(r.home_np_xg),
                float(r.away_np_xg_difference),
                float(r.away_ppda), float(r.home_ppda),
                int(r.away_deep_completions),
                int(r.home_deep_completions),
            ))
        print(f"  Transformed to {len(long_rows)} long rows "
              f"(expected {2 * len(df)}).")

        # 5. Write in a transaction.
        seasons = sorted(SEASON_MAP.keys())
        print(f"\nWiping team_match_stats for {seasons} and reloading...")
        con.execute("BEGIN TRANSACTION")
        try:
            for season in seasons:
                con.execute(
                    "DELETE FROM team_match_stats WHERE season = ?",
                    [season],
                )
            con.executemany(
                """
                INSERT INTO team_match_stats (
                    game_id, team, side, season, opponent,
                    points, expected_points,
                    goals, opponent_goals,
                    xg, opponent_xg, np_xg, opponent_np_xg,
                    np_xg_difference,
                    ppda, opponent_ppda,
                    deep_completions, opponent_deep_completions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?)
                """,
                long_rows,
            )
            inserted = con.execute(
                "SELECT COUNT(*) FROM team_match_stats"
            ).fetchone()[0]
            if inserted != len(long_rows):
                raise SystemExit(
                    f"Insert mismatch: tried {len(long_rows)}, "
                    f"see {inserted}. Rolling back."
                )

            con.execute("COMMIT")
            print(f"\nCOMMITTED. {inserted} team-match rows written.")
        except Exception:
            print("!!! Error during insert, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 6. Sanity output.
        print("\n--- Rows per season + side ---")
        for r in con.execute(
            """
            SELECT season, side, COUNT(*) AS n,
                   COUNT(DISTINCT team) AS n_teams,
                   COUNT(DISTINCT game_id) AS n_games
            FROM team_match_stats
            GROUP BY season, side
            ORDER BY season, side
            """
        ).fetchall():
            print(f"  {r[0]} {r[1]:<5} rows={r[2]:>4} "
                  f"teams={r[3]:>3} games={r[4]:>4}")

        print("\n--- Top 5 teams by avg opponent_xg "
              "(low = strong defense) in 2025-2026 ---")
        for r in con.execute(
            """
            SELECT team,
                   COUNT(*) AS n_matches,
                   ROUND(AVG(opponent_xg), 3) AS avg_opp_xg,
                   ROUND(AVG(xg), 3) AS avg_own_xg,
                   ROUND(AVG(opponent_goals), 3) AS avg_goals_against,
                   ROUND(AVG(ppda), 2) AS avg_ppda
            FROM team_match_stats
            WHERE season = '2025-2026'
            GROUP BY team
            ORDER BY avg_opp_xg ASC
            LIMIT 5
            """
        ).fetchall():
            print(f"  {r[0]:<22} matches={r[1]} "
                  f"avg_opp_xg={r[2]} avg_own_xg={r[3]} "
                  f"avg_GA={r[4]} avg_ppda={r[5]}")

        print("\n--- Bottom 5 (weakest defenses) in 2025-2026 ---")
        for r in con.execute(
            """
            SELECT team,
                   COUNT(*) AS n_matches,
                   ROUND(AVG(opponent_xg), 3) AS avg_opp_xg,
                   ROUND(AVG(xg), 3) AS avg_own_xg,
                   ROUND(AVG(opponent_goals), 3) AS avg_goals_against,
                   ROUND(AVG(ppda), 2) AS avg_ppda
            FROM team_match_stats
            WHERE season = '2025-2026'
            GROUP BY team
            ORDER BY avg_opp_xg DESC
            LIMIT 5
            """
        ).fetchall():
            print(f"  {r[0]:<22} matches={r[1]} "
                  f"avg_opp_xg={r[2]} avg_own_xg={r[3]} "
                  f"avg_GA={r[4]} avg_ppda={r[5]}")

        print("\n--- Liverpool's last 5 matches in 2025-2026 ---")
        for r in con.execute(
            """
            SELECT g.match_date, tms.opponent, tms.side,
                   tms.goals, tms.opponent_goals,
                   ROUND(tms.xg, 2) AS xg,
                   ROUND(tms.opponent_xg, 2) AS opp_xg,
                   ROUND(tms.ppda, 1) AS ppda
            FROM team_match_stats tms
            JOIN games g USING (game_id)
            WHERE tms.team = 'Liverpool' AND tms.season = '2025-2026'
            ORDER BY g.match_date DESC
            LIMIT 5
            """
        ).fetchall():
            score = f"{r[3]}-{r[4]}"
            xg_str = f"{r[5]}-{r[6]}"
            print(f"  {r[0]}  ({r[2]:<4}) vs {r[1]:<22} "
                  f"score={score:<5} xG={xg_str:<10} ppda={r[7]}")
    finally:
        con.close()


if __name__ == "__main__":
    main()