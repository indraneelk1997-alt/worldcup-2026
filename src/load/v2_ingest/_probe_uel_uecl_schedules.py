"""
_probe_uel_uecl_schedules.py — S24 probe (deletable). Confirm the new overlay
entries (UEFA-Europa League, UEFA-Conference League) are recognised by
soccerdata and that read_schedule returns the columns ingest_fbref.py needs —
BEFORE committing to the ~70-min per-season player-match fetch.

Cheap: read_schedule only (one page per league-season). The team_match /
player_match column shapes are the SAME soccerdata code path already validated
for UCL (S21/S22), and the loader's FBREF_COL_MAP fails loud on drift, so this
probe deliberately does NOT do the expensive per-game player fetch.

    uv run python src/load/v2_ingest/_probe_uel_uecl_schedules.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from soccerdata import FBref  # noqa: E402

LEAGUES = ["UEFA-Europa League", "UEFA-Conference League"]
SEASONS = ["2024-2025", "2025-2026"]
REPORT = Path("data/raw/uefa/_probe_uel_uecl_schedules.txt")

# what load_games (Section A) leans on — concepts the schedule must carry.
NEEDED = ["date", "home_team", "away_team", "score"]


def main() -> int:
    lines: list[str] = []
    summary: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    rc = 0
    try:
        avail = set(FBref.available_leagues())
        for lg in LEAGUES:
            w(f"available_leagues has {lg!r}: {lg in avail}")
        missing = [lg for lg in LEAGUES if lg not in avail]
        if missing:
            raise RuntimeError(f"overlay not picked up for {missing} — "
                               f"re-run setup_soccerdata_overlay.py")

        printed_cols = False
        for lg in LEAGUES:
            w(f"\n==== {lg} ====")
            try:
                sched = FBref(leagues=[lg], seasons=SEASONS).read_schedule().reset_index()
            except Exception as e:
                w(f"  read_schedule FAILED: {type(e).__name__}: {e}")
                summary.append(f"{lg}: read_schedule FAILED")
                continue

            if not printed_cols:
                w(f"  columns ({len(sched.columns)}): {list(sched.columns)}")
                miss = [c for c in NEEDED if c not in sched.columns]
                w(f"  loader-needed cols present: {not miss}"
                  + (f"  MISSING {miss}" if miss else ""))
                printed_cols = True

            by_season = sched.groupby("season").size().to_dict() if "season" in sched.columns else {}
            w(f"  total schedule rows: {len(sched)} | by season: {by_season}")
            if "round" in sched.columns:
                w(f"  rounds/stages: {sorted(sched['round'].dropna().unique())[:10]}")
            show = [c for c in ["season", "date", "home_team", "away_team", "score", "round"]
                    if c in sched.columns]
            w("  sample:\n" + sched[show].head(4).to_string(index=False))
            summary.append(f"{lg}: {len(sched)} rows {by_season}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("UEL/UECL schedule probe done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
