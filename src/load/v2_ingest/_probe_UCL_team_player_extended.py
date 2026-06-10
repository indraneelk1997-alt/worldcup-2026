"""
S21 Phase 2c probe — UCL extended shape probe (team xG + player summary).

Two steps, sequential:

  Step 1: read_team_match_stats(stat_type='shooting') for UCL 2024-25.
          ~4 min wall (~36 fresh team-page fetches at FBref's 7s rate
          limit). Caches don't overlap with the 'schedule' run from
          Phase 2b — different filemask. Goal: confirm xG column shape.

  Step 2: read_player_match_stats(stat_type='summary') for UCL 2024-25.
          ~22 min wall (~189 per-match fetches). Captures the per-
          player-per-match shape the V1.04 FBref loader will consume.

          IMPORTANT SIDE EFFECT: each fetch caches the full
          /en/matches/<id>/ HTML at
            ~/soccerdata/data/FBref/match_<game_id>.html
          Those files contain ALL 6 stat tables per team
          (summary, passing, pass_types, defense, possession, misc,
          keeper). After this run we can extract the 4 stat_types
          soccerdata doesn't expose via a custom parser — zero
          additional HTTP cost.

Progress is visible via soccerdata's own logger (one INFO line per
match: "[i/189] Retrieving game with id=..."). Step 2 is long enough
that we want that signal.

Does NOT touch DB. Deletable after design doc lands.

Run:
    uv run python src/load/v2_ingest/_probe_UCL_team_player_extended.py
"""

from __future__ import annotations

import sys
import time
import traceback

UCL_LEAGUE_KEY = "UEFA-Champions League"
UCL_SEASON = "2024-2025"


def section(title: str) -> None:
    bar = "=" * 64
    print(f"\n{bar}\n  {title}\n{bar}")


def report_df(df, name: str) -> None:
    print(f"\n  {name}: {len(df)} rows")
    print(f"  index names: {df.index.names}")
    cols = df.columns.tolist()
    print(f"  columns ({len(cols)}):")
    for c in cols:
        print(f"    - {c!r}")
    print(f"\n  dtypes:")
    for c, dt in df.dtypes.items():
        print(f"    {str(c)[:45]:45} {dt}")
    print(f"\n  head(5):")
    print(df.head(5).to_string())


def main() -> int:
    section("S21 Phase 2c — UCL extended shape probe")
    print(f"  league: {UCL_LEAGUE_KEY}")
    print(f"  season: {UCL_SEASON}")
    print(f"  expected wall: ~4 min (Step 1) + ~22 min (Step 2) = ~26 min")
    print(f"  (cached fetches are instant; first runs respect rate limit)")

    try:
        from soccerdata import FBref
    except Exception as e:
        print(f"FAILED import: {type(e).__name__}: {e}")
        return 1

    if UCL_LEAGUE_KEY not in FBref.available_leagues():
        print(f"FAIL — '{UCL_LEAGUE_KEY}' not in FBref.available_leagues().")
        print(f"  Run: uv run python src/tools/setup_soccerdata_overlay.py")
        return 2

    scraper = FBref(leagues=[UCL_LEAGUE_KEY], seasons=UCL_SEASON)

    # ---- Step 1 ----
    section("Step 1: read_team_match_stats(stat_type='shooting')  (~4 min)")
    print(f"  NB: still all-comps contaminated like the 'schedule' probe;")
    print(f"  we just want column shape here, especially xG presence.")
    t0 = time.time()
    try:
        team_shooting = scraper.read_team_match_stats(stat_type="shooting")
        report_df(team_shooting, "team_match(shooting)")
        xg_cols = [c for c in team_shooting.columns if "xg" in str(c).lower()]
        print(f"\n  xG-bearing columns: {xg_cols or 'none'}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        # don't abort — try step 2 anyway
    print(f"\n  step 1 elapsed: {time.time() - t0:.1f}s")

    # ---- Step 2 ----
    section("Step 2: read_player_match_stats(stat_type='summary')  (~22 min)")
    print(f"  ~189 fetches; soccerdata logs '[i/189] Retrieving game with")
    print(f"  id=...' every ~7s — that's how you know it's still alive.")
    print(f"  Cached match HTMLs land at ~/soccerdata/data/FBref/match_*.html")
    print(f"  and enable extended-stat parsing later for free.")
    t0 = time.time()
    try:
        player_summary = scraper.read_player_match_stats(stat_type="summary")
        report_df(player_summary, "player_match(summary)")
        # quick diagnostics
        print(f"\n  --- distinct leagues in result: ---")
        try:
            ls = (
                player_summary.index.get_level_values("league")
                .unique().tolist()
            )
            print(f"    {ls}")
        except Exception as e:
            print(f"    inspection failed: {type(e).__name__}: {e}")
        print(f"\n  --- distinct seasons in result: ---")
        try:
            ss = (
                player_summary.index.get_level_values("season")
                .unique().tolist()
            )
            print(f"    {ss}")
        except Exception as e:
            print(f"    inspection failed: {type(e).__name__}: {e}")
        try:
            n_games = player_summary.index.get_level_values("game").nunique()
            n_players = (
                player_summary.index.get_level_values("player").nunique()
            )
            print(f"\n  distinct games:   {n_games}")
            print(f"  distinct players: {n_players}")
        except Exception:
            pass
        xg_cols = [
            c for c in player_summary.columns if "xg" in str(c).lower()
        ]
        print(f"\n  xG-bearing columns: {xg_cols or 'none'}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
    print(f"\n  step 2 elapsed: {time.time() - t0:.1f}s")

    section("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
