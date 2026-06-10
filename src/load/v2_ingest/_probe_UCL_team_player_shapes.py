"""
S21 Phase 2b probe — FBref team-match shape for UCL 2024-25.

Live: read_team_match_stats() for UCL 2024-25. FBref's per-team
match-log pages — ~36 fetches at 7s rate limit ≈ 4 min wall first
run, instant on cache hits.

Captures column shape for the design-doc schema-delta discussion:
  - what xG / goal / possession columns FBref returns
  - whether the score is split or text
  - game_id format (hash vs integer)
  - any unexpected MultiIndex columns

Companion source-read of read_player_match_stats across all 6
stat_types (summary, passing, defense, possession, misc, keeper)
is captured separately in the S21 design doc — not run live here
because it costs ~22 min × 6 stat_types wall.

Does NOT touch the DB. Deletable after docs/v104_ingest_competitions.md
lands.

Run:
    uv run python src/load/v2_ingest/_probe_UCL_team_player_shapes.py
"""

from __future__ import annotations

import sys
import traceback

UCL_LEAGUE_KEY = "UEFA-Champions League"
UCL_SEASON = "2024-2025"


def main() -> int:
    bar = "=" * 64
    print(f"\n{bar}\n  S21 Phase 2b — UCL team-match shape probe\n{bar}")
    print(f"  league: {UCL_LEAGUE_KEY}")
    print(f"  season: {UCL_SEASON}")
    print(f"  expected wall: ~4 min (FBref rate limit 7s × ~36 team pages)")

    try:
        from soccerdata import FBref
    except Exception as e:
        print(f"  FAILED import: {type(e).__name__}: {e}")
        return 1

    leagues = FBref.available_leagues()
    if UCL_LEAGUE_KEY not in leagues:
        print(f"\n  FAIL — '{UCL_LEAGUE_KEY}' not in FBref.available_leagues().")
        print(f"  Total: {len(leagues)}. Run:")
        print(f"    uv run python src/tools/setup_soccerdata_overlay.py")
        return 2

    print(f"\nStep 1: configure FBref(leagues=['{UCL_LEAGUE_KEY}'], "
          f"seasons='{UCL_SEASON}')")
    scraper = FBref(leagues=[UCL_LEAGUE_KEY], seasons=UCL_SEASON)

    print(f"\nStep 2: read_team_match_stats() — this takes ~4 min on first run")
    print(f"        (cached fetches are instant on subsequent runs)")
    try:
        team_match = scraper.read_team_match_stats()
    except TypeError as e:
        # signature might require stat_type — surface it
        print(f"  TypeError: {e}")
        print(f"  Trying with stat_type='schedule'...")
        try:
            team_match = scraper.read_team_match_stats(stat_type="schedule")
        except Exception as e2:
            print(f"  FAILED with stat_type fallback: "
                  f"{type(e2).__name__}: {e2}")
            traceback.print_exc()
            return 3
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 3

    print(f"\n  rows: {len(team_match)}")
    print(f"  index names: {team_match.index.names}")
    print(f"  columns type: {type(team_match.columns).__name__} "
          f"(MultiIndex if FBref returns grouped stats)")
    print(f"  columns ({len(team_match.columns)}):")
    for c in team_match.columns.tolist():
        print(f"    - {c!r}")

    print(f"\n  dtypes:")
    for c, dt in team_match.dtypes.items():
        print(f"    {str(c)[:45]:45} {dt}")

    print(f"\n  head(5):")
    print(team_match.head(5).to_string())

    # --- summary diagnostics for design doc ---
    print(f"\n  --- distinct leagues in index: ---")
    try:
        ls = team_match.index.get_level_values("league").unique().tolist()
        print(f"    {ls}")
    except Exception as e:
        print(f"    inspection failed: {type(e).__name__}: {e}")

    print(f"\n  --- distinct seasons in index: ---")
    try:
        ss = team_match.index.get_level_values("season").unique().tolist()
        print(f"    {ss}")
    except Exception as e:
        print(f"    inspection failed: {type(e).__name__}: {e}")

    flat_cols = [str(c).lower() for c in team_match.columns]
    xg_cols = [c for c in team_match.columns if "xg" in str(c).lower()]
    goals_cols = [c for c in team_match.columns if "goal" in str(c).lower()]
    print(f"\n  --- key column groups present? ---")
    print(f"    xG-bearing:     {xg_cols or 'none'}")
    print(f"    goals-bearing:  {goals_cols or 'none'}")

    print(f"\n  ✅ probe done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
