"""
validate_v104_ingest.py  —  S19 post-load DB validation.

Read-only. After the Big-3 batch load, prints a coverage report across
the 7 league-bearing tables plus FK integrity spot-checks. Helps
confirm the full top-5 ingest is consistent without re-running the
loader or eyeballing 6 separate load outputs.

Run from repo root:
    uv run python src/tools/validate_v104_ingest.py

Expected post-S19 highlights:
  - games: 5 leagues × 2 seasons = 10 (league, season) pairs.
    Counts: PL/La Liga/Serie A/Ligue 1 = 380 each;
    Bundesliga = 306 (18 teams × 34 matchdays).
  - team_match_stats: exactly 2 × games per (league, season).
  - team_season_strength_v103 / league_averages_v103 /
    player_season_stats / fixtures: PL ONLY — these are derived state,
    not maintained by the V1.04 ingest path (decision (a), S18).
"""
from __future__ import annotations

from pathlib import Path
import duckdb

DB_PATH = Path("data/processed/worldcup.duckdb")

LEAGUE_TABLES = [
    "games",
    "team_match_stats",
    "player_match_stats",
    "team_season_strength_v103",
    "league_averages_v103",
    "fixtures",
    "player_season_stats",
]

# Per S17 mixed-enforcement policy — these tables are nullable at the
# DB level; the V1.04 loader enforces non-nullity in app code.
FK_BLOCKED = {"games", "fixtures"}

# Tables we expect to remain PL-only after S19 (derived state, not
# part of the V1.04 ingest scope).
PL_ONLY_TABLES = {
    "team_season_strength_v103",
    "league_averages_v103",
    "player_season_stats",
    "fixtures",
}


def section(s: str) -> None:
    print()
    print("=" * 76)
    print(s)
    print("=" * 76)


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # 1) Coverage matrix
        section("1) Coverage matrix — rows per (league, season) per table")
        for t in LEAGUE_TABLES:
            tag = "  (expected PL-only)" if t in PL_ONLY_TABLES else ""
            print(f"\n  --- {t}{tag} ---")
            rows = con.execute(
                f"SELECT league, season, count(*) AS n FROM {t} "
                f"GROUP BY league, season ORDER BY league, season"
            ).fetchall()
            if not rows:
                print(f"    (empty)")
                continue
            for league, season, n in rows:
                lstr = league if league is not None else "<NULL>"
                sstr = season if season is not None else "<NULL>"
                print(f"    {lstr:<22} {sstr:<11} {n:>8,}")

        # 2) NULL-league audit
        section("2) NULL `league` audit")
        for t in LEAGUE_TABLES:
            null_count = con.execute(
                f"SELECT count(*) FROM {t} WHERE league IS NULL"
            ).fetchone()[0]
            total = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            note = " (FK-blocked; app-code enforces)" if t in FK_BLOCKED else ""
            flag = "  !! REVIEW" if null_count > 0 else "  OK"
            print(f"    [{t:<28}] nulls={null_count:>5}/{total:<6}{note}{flag}")

        # 3) Game counts per (league, season)
        section("3) Game counts per (league, season)")
        rows = con.execute(
            "SELECT league, season, count(*) AS n FROM games "
            "GROUP BY league, season ORDER BY league, season"
        ).fetchall()
        for league, season, n in rows:
            print(f"    {league:<22} {season:<11} {n:>6} games")

        # 4) Team counts per (league, season)
        section("4) Distinct teams per (league, season) — from team_match_stats")
        rows = con.execute(
            "SELECT league, season, COUNT(DISTINCT team) AS n_teams "
            "FROM team_match_stats GROUP BY league, season "
            "ORDER BY league, season"
        ).fetchall()
        for league, season, n in rows:
            print(f"    {league:<22} {season:<11} {n:>4} teams")

        # 5) team_match_stats invariant: 2 rows per game per side
        section("5) Invariant: team_match_stats rows == 2 × games per (league, season)")
        rows = con.execute(
            """
            SELECT g.league, g.season,
                   COUNT(DISTINCT g.game_id) AS n_games,
                   COUNT(*) AS n_tms_rows,
                   2 * COUNT(DISTINCT g.game_id) AS expected
            FROM games g
            JOIN team_match_stats t USING (game_id)
            GROUP BY g.league, g.season
            ORDER BY g.league, g.season
            """
        ).fetchall()
        for league, season, ng, ntms, expected in rows:
            ok = "OK" if ntms == expected else "!! MISMATCH"
            print(f"    {league:<22} {season:<11} "
                  f"games={ng:>4}  team_match={ntms:>5}  "
                  f"expected={expected:>5}  {ok}")

        # 6) Player counts per (league, season)
        section("6) Distinct players per (league, season) — from player_match_stats")
        rows = con.execute(
            "SELECT league, season, COUNT(DISTINCT player_id) AS n_players "
            "FROM player_match_stats GROUP BY league, season "
            "ORDER BY league, season"
        ).fetchall()
        for league, season, n in rows:
            print(f"    {league:<22} {season:<11} {n:>5} distinct players")

        # 7) FK integrity spot-checks
        section("7) FK integrity spot-checks (orphan rows; expect 0)")
        checks = [
            ("player_match_stats.player_id not in players",
             "SELECT count(*) FROM player_match_stats pms "
             "LEFT JOIN players p USING (player_id) "
             "WHERE p.player_id IS NULL"),
            ("player_match_stats.game_id not in games",
             "SELECT count(*) FROM player_match_stats pms "
             "LEFT JOIN games g USING (game_id) "
             "WHERE g.game_id IS NULL"),
            ("team_match_stats.game_id not in games",
             "SELECT count(*) FROM team_match_stats t "
             "LEFT JOIN games g USING (game_id) "
             "WHERE g.game_id IS NULL"),
        ]
        for desc, query in checks:
            n = con.execute(query).fetchone()[0]
            flag = "  !! REVIEW" if n > 0 else "  OK"
            print(f"    {desc}: {n}{flag}")

        # 8) Grand totals
        section("8) Grand totals (all tables touched by V1.04 ingest)")
        for t in LEAGUE_TABLES + ["players",
                                  "team_match_fbref", "player_match_fbref"]:
            total = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"    {t:<30} {total:>10,}")

        # 9) Player carryover (cross-league overlap)
        section("9) Players appearing in >1 league (carryover/transfers)")
        n_multi = con.execute(
            """
            SELECT count(*) FROM (
                SELECT player_id
                FROM player_match_stats
                GROUP BY player_id
                HAVING COUNT(DISTINCT league) > 1
            )
            """
        ).fetchone()[0]
        print(f"    {n_multi} player_ids appear in 2+ leagues "
              f"(cross-league transfers / shared player_ids)")

        # 10) FBref source-separated tables (Option C, S22). These live
        # in their own tables, so the Understat-table sections above
        # (inner joins) silently skip FBref leagues — validated here.
        section("10) FBref tables (Option C) — team_match_fbref / player_match_fbref")

        print("\n  --- games by source ---")
        for src, n in con.execute(
            "SELECT COALESCE(source, '<NULL>') AS s, count(*) FROM games "
            "GROUP BY s ORDER BY s"
        ).fetchall():
            print(f"    {src:<12} {n:>6,}")

        for t in ("team_match_fbref", "player_match_fbref"):
            print(f"\n  --- {t}: rows per (league, season) ---")
            rows = con.execute(
                f"SELECT league, season, count(*) FROM {t} "
                f"GROUP BY league, season ORDER BY league, season"
            ).fetchall()
            if not rows:
                print("    (empty)")
            for league, season, n in rows:
                print(f"    {league:<24} {season:<11} {n:>8,}")

        print("\n  --- invariant: team_match_fbref == 2 × FBref games ---")
        for league, season, ng, nt, exp in con.execute(
            """SELECT g.league, g.season, COUNT(DISTINCT g.game_id),
                      COUNT(*), 2 * COUNT(DISTINCT g.game_id)
               FROM games g JOIN team_match_fbref t USING (game_id)
               WHERE g.source = 'fbref'
               GROUP BY g.league, g.season ORDER BY g.league, g.season"""
        ).fetchall():
            ok = "OK" if nt == exp else "!! MISMATCH"
            print(f"    {league:<24} {season:<11} games={ng:>4} "
                  f"team_match={nt:>5} expected={exp:>5}  {ok}")

        print("\n  --- distinct players (player_match_fbref) ---")
        for league, season, n in con.execute(
            "SELECT league, season, COUNT(DISTINCT player_id) "
            "FROM player_match_fbref GROUP BY league, season "
            "ORDER BY league, season"
        ).fetchall():
            print(f"    {league:<24} {season:<11} {n:>5} distinct players")

        print("\n  --- score cross-check: games goals == team_match_fbref goals "
              "(decision c) ---")
        mismatch = con.execute(
            """SELECT count(*) FROM games g
               JOIN team_match_fbref th ON th.game_id = g.game_id AND th.side = 'home'
               JOIN team_match_fbref ta ON ta.game_id = g.game_id AND ta.side = 'away'
               WHERE g.source = 'fbref'
                 AND (th.goals != g.home_goals OR ta.goals != g.away_goals)"""
        ).fetchone()[0]
        print(f"    games with score/team_match goal mismatch: {mismatch}"
              f"{'  !! REVIEW' if mismatch else '  OK'}")

        print("\n  --- FK integrity (FBref tables; expect 0 orphans) ---")
        for desc, q in [
            ("player_match_fbref.game_id not in games",
             "SELECT count(*) FROM player_match_fbref p "
             "LEFT JOIN games g USING (game_id) WHERE g.game_id IS NULL"),
            ("player_match_fbref.player_id not in players",
             "SELECT count(*) FROM player_match_fbref p "
             "LEFT JOIN players pl USING (player_id) WHERE pl.player_id IS NULL"),
            ("team_match_fbref.game_id not in games",
             "SELECT count(*) FROM team_match_fbref t "
             "LEFT JOIN games g USING (game_id) WHERE g.game_id IS NULL"),
        ]:
            n = con.execute(q).fetchone()[0]
            print(f"    {desc}: {n}{'  !! REVIEW' if n else '  OK'}")

        print("\n  --- dob coverage (FBref players, id >= 50M) ---")
        with_dob, total_fb = con.execute(
            "SELECT count(player_dob), count(*) FROM players "
            "WHERE player_id >= 50000000"
        ).fetchone()
        print(f"    FBref players: {total_fb} | with dob: {with_dob}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
