"""
S20 Phase 2a: probe Path A (extend soccerdata via league_dict overlay) for CL.

Validates whether adding a single custom entry to
~/soccerdata/config/league_dict.json is sufficient to unlock UEFA
Champions League data via the existing FBref scraper, without writing
any loader code.

Sequence:
  1. Write/merge ~/soccerdata/config/league_dict.json with the CL entry.
     Backs up any pre-existing file as .bak first.
  2. Import soccerdata fresh (in this process — script designed to be
     run as its own `uv run python ...` invocation).
  3. Confirm 'UEFA-Champions League' now appears in FBref.available_leagues().
  4. FBref(...).read_schedule() for CL 2024-2025; print shape + head.

Stops there. Does NOT call read_player_match_stats / read_team_match_stats
(those iterate many matches at FBref's rate-limited pace; defer to
real loader after design doc lands).

Does NOT touch DB. Deletable after S20 once docs/v104_ingest_competitions.md
captures the finding.

Run:
    uv run python src/load/v2_ingest/_probe_cl_path_a.py

Reverting the overlay (if probe fails / you don't want it persisted):
    rm ~/soccerdata/config/league_dict.json
    # (or restore from ~/soccerdata/config/league_dict.json.bak if it existed)
"""

from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

LEAGUE_DICT_PATH = Path.home() / "soccerdata" / "config" / "league_dict.json"
LEAGUE_KEY = "UEFA-Champions League"

CL_ENTRY = {
    LEAGUE_KEY: {
        # Verified from FBref's /en/comps/ catalog (Phase 2a v2):
        # row in comps_intl_club_cup, exact competition_name.
        "FBref": "UEFA Champions League",
        # WhoScored guess (unverified — not exercised by this FBref probe).
        "WhoScored": "Europe - Champions League",
        "season_start": "Sep",
        "season_end": "May",
    }
}


def write_overlay() -> None:
    LEAGUE_DICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LEAGUE_DICT_PATH.exists():
        bak = LEAGUE_DICT_PATH.with_suffix(".json.bak")
        shutil.copy2(LEAGUE_DICT_PATH, bak)
        print(f"  [overlay] existing file backed up → {bak}")
        existing = json.loads(LEAGUE_DICT_PATH.read_text("utf8"))
        merged = {**existing, **CL_ENTRY}
        LEAGUE_DICT_PATH.write_text(json.dumps(merged, indent=2), "utf8")
    else:
        LEAGUE_DICT_PATH.write_text(json.dumps(CL_ENTRY, indent=2), "utf8")
    print(f"  [overlay] wrote {LEAGUE_DICT_PATH}")
    print(f"  [overlay] entry:")
    print("    " + json.dumps(CL_ENTRY, indent=2).replace("\n", "\n    "))


def main() -> int:
    bar = "=" * 64
    print(f"\n{bar}")
    print("  S20 Phase 2a — Path A probe: CL via league_dict overlay")
    print(bar)

    print("\nStep 1: write overlay file")
    try:
        write_overlay()
    except Exception as e:
        print(f"  FAILED to write overlay: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    print("\nStep 2: import soccerdata (post-overlay)")
    try:
        from soccerdata import FBref
    except Exception as e:
        print(f"  FAILED import: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 2

    print(f"\nStep 3: confirm '{LEAGUE_KEY}' in FBref.available_leagues()")
    try:
        leagues = sorted(FBref.available_leagues())
        present = LEAGUE_KEY in leagues
        print(f"  total now: {len(leagues)}")
        print(f"  '{LEAGUE_KEY}' present: {present}")
        if not present:
            print(f"  FAIL — entry written but didn't surface. Full list:")
            for L in leagues:
                print(f"    {L}")
            return 3
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 3

    print(f"\nStep 4: FBref(leagues=['{LEAGUE_KEY}'], seasons='2024-2025').read_schedule()")
    try:
        scraper = FBref(leagues=[LEAGUE_KEY], seasons="2024-2025")
        schedule = scraper.read_schedule()
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        print(f"\n  ↑ Likely cause: '{CL_ENTRY[LEAGUE_KEY]['FBref']}' is not")
        print(f"    FBref's actual competition name string. Alternates to try:")
        print(f"      'UEFA Champions League'")
        print(f"      'Champions Lg'")
        print(f"      Check fbref.com/en/comps/8/ for the on-page label.")
        return 4

    print(f"  rows: {len(schedule)}")
    print(f"  index names: {schedule.index.names}")
    print(f"  columns ({len(schedule.columns)}): {schedule.columns.tolist()}")
    print(f"\n  head(5):")
    print(schedule.head(5).to_string())

    print(f"\n  --- distinct leagues in result: ---")
    try:
        # league is MultiIndex level 0 per soccerdata convention
        leagues_in_df = (
            schedule.index.get_level_values("league").unique().tolist()
            if "league" in schedule.index.names
            else "n/a (no 'league' index level)"
        )
        print(f"    {leagues_in_df}")
    except Exception as e:
        print(f"    inspection failed: {type(e).__name__}: {e}")

    print(f"\n  --- distinct seasons in result: ---")
    try:
        seasons_in_df = (
            schedule.index.get_level_values("season").unique().tolist()
            if "season" in schedule.index.names
            else "n/a (no 'season' index level)"
        )
        print(f"    {seasons_in_df}")
    except Exception as e:
        print(f"    inspection failed: {type(e).__name__}: {e}")

    print("\n  ✅ Path A viable for CL via FBref.")
    print("  Next: commit overlay to data/config/league_dict.json + setup script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
