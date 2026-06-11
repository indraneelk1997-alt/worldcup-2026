"""
S25 — StatsBomb Open sidecar loader (one tournament at a time).

Loads matches/events/360-frames for a StatsBomb open-data tournament into the
self-contained sidecar (docs/statsbomb_ingest_design.md): statsbomb_match /
statsbomb_event / statsbomb_frame / statsbomb_frame_meta. ZERO links into
players/games — the cross-walk to our world is a SEPARATE later resolver pass.

Observed shapes (S25 Euro-2024 pilot, match 3930158), not inferred:
  * events(mid, fmt='dict') -> lossless nested events; typed cols + `raw`
    JSON both built from the SAME dict in one pass.
  * frames(mid, fmt='dict') -> list of {event_uuid, visible_area, match_id,
    freeze_frame:[{teammate,actor,keeper,location:[x,y]}]}. The df path is
    broken (InvalidIndexError) so we always use dict + normalize ourselves.
  * full-360 frames are anonymized (no player_id) -> occupancy truth only.

Idempotent: INSERT OR IGNORE on every PK -> re-running a tournament is a
no-op. Per-match inserts bound memory (~2M frame rows for a full tournament).

Default DRY-RUN (fetches + counts, no writes; also warms the requests-cache
so --apply writes from cache). Pass --apply to write.

    # dry-run Euro 2024 (counts only)
    uv run python src/load/v2_ingest/ingest_statsbomb.py --tournament euro2024
    # quick 2-match dry-run
    uv run python src/load/v2_ingest/ingest_statsbomb.py --tournament euro2024 --limit 2
    # live load
    uv run python src/load/v2_ingest/ingest_statsbomb.py --tournament euro2024 --apply
"""

from __future__ import annotations

import argparse
import json
import sys

import duckdb
import pandas as pd
from statsbombpy import sb

DB_PATH = "data/processed/worldcup.duckdb"

# (competition_id, season_id) verified S25 via sb.competitions().
TOURNAMENTS = {
    "wc2022":   (43, 106),    # FIFA World Cup 2022       (has 360)
    "euro2024": (55, 282),    # UEFA Euro 2024            (has 360)
    "copa2024": (223, 282),   # Copa America 2024         (NO 360)
    "afcon2023": (1267, 107),  # African Cup of Nations 23 (has 360)
}

MATCH_COLS = [
    "match_id", "competition_id", "season_id", "match_date", "kick_off",
    "match_week", "competition_stage_id", "competition_stage",
    "home_team_id", "home_team", "away_team_id", "away_team",
    "home_score", "away_score", "stadium_id", "stadium",
    "referee_id", "referee",
]


def _nested(d: dict, *path):
    """Safe nested get: _nested(ev, 'team', 'name')."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _end_location(ev: dict):
    """Coalesce the type-specific end-location ([x,y] or [x,y,z])."""
    for key in ("pass", "carry", "shot", "goalkeeper"):
        loc = _nested(ev, key, "end_location")
        if isinstance(loc, list) and len(loc) >= 2:
            return loc[0], loc[1]
    return None, None


def _coalesce_named(ev: dict, attr: str):
    """First {attr:{name}} found among the event's type-specific sub-dicts."""
    for v in ev.values():
        if isinstance(v, dict) and isinstance(v.get(attr), dict):
            return v[attr].get("name")
    return None


def parse_event(ev: dict, cid: int, sid: int) -> dict:
    loc = ev.get("location")
    x = loc[0] if isinstance(loc, list) and len(loc) >= 2 else None
    y = loc[1] if isinstance(loc, list) and len(loc) >= 2 else None
    end_x, end_y = _end_location(ev)
    return {
        "id": ev.get("id"),
        "match_id": ev.get("match_id"),
        "competition_id": cid,
        "season_id": sid,
        "event_index": ev.get("index"),
        "period": ev.get("period"),
        "timestamp": ev.get("timestamp"),
        "minute": ev.get("minute"),
        "second": ev.get("second"),
        "type": _nested(ev, "type", "name"),
        "possession": ev.get("possession"),
        "possession_team": _nested(ev, "possession_team", "name"),
        "possession_team_id": _nested(ev, "possession_team", "id"),
        "team_id": _nested(ev, "team", "id"),
        "team": _nested(ev, "team", "name"),
        "player_id": _nested(ev, "player", "id"),
        "player": _nested(ev, "player", "name"),
        "position": _nested(ev, "position", "name"),
        "play_pattern": _nested(ev, "play_pattern", "name"),
        "x": x, "y": y, "end_x": end_x, "end_y": end_y,
        "duration": ev.get("duration"),
        "outcome": _coalesce_named(ev, "outcome"),
        "body_part": _coalesce_named(ev, "body_part"),
        "under_pressure": bool(ev["under_pressure"]) if "under_pressure" in ev else None,
        "pass_recipient_id": _nested(ev, "pass", "recipient", "id"),
        "shot_xg": _nested(ev, "shot", "statsbomb_xg"),
        "raw": json.dumps(ev, ensure_ascii=False),
    }


def parse_frames(frame_list: list, mid: int):
    """Return (frame_rows, meta_rows) from a frames(fmt='dict') list."""
    frame_rows, meta_rows = [], []
    for rec in frame_list:
        euid = rec.get("event_uuid")
        meta_rows.append({
            "event_uuid": euid, "match_id": mid,
            "visible_area": json.dumps(rec.get("visible_area"), ensure_ascii=False),
        })
        for i, a in enumerate(rec.get("freeze_frame", [])):
            aloc = a.get("location") or [None, None]
            frame_rows.append({
                "event_uuid": euid, "match_id": mid, "frame_idx": i,
                "x": aloc[0] if len(aloc) >= 2 else None,
                "y": aloc[1] if len(aloc) >= 2 else None,
                "teammate": a.get("teammate"), "actor": a.get("actor"),
                "keeper": a.get("keeper"),
            })
    return frame_rows, meta_rows


def _insert(con, df: pd.DataFrame, sql: str, reg: str) -> None:
    con.register(reg, df)
    con.execute(sql)
    con.unregister(reg)


EVENT_INSERT = """
INSERT OR IGNORE INTO statsbomb_event
  (id, match_id, competition_id, season_id, event_index, period, timestamp,
   minute, second, type, possession, possession_team, possession_team_id,
   team_id, team, player_id, player, position, play_pattern, x, y, end_x,
   end_y, duration, outcome, body_part, under_pressure, pass_recipient_id,
   shot_xg, raw)
SELECT id, match_id, competition_id, season_id, event_index, period, timestamp,
   minute, second, type, possession, possession_team, possession_team_id,
   team_id, team, player_id, player, position, play_pattern, x, y, end_x,
   end_y, duration, outcome, body_part, under_pressure, pass_recipient_id,
   shot_xg, CAST(raw AS JSON)
FROM df_ev
"""

FRAME_INSERT = """
INSERT OR IGNORE INTO statsbomb_frame
  (event_uuid, match_id, frame_idx, x, y, teammate, actor, keeper)
SELECT event_uuid, match_id, frame_idx, x, y, teammate, actor, keeper
FROM df_fr
"""

META_INSERT = """
INSERT OR IGNORE INTO statsbomb_frame_meta (event_uuid, match_id, visible_area)
SELECT event_uuid, match_id, CAST(visible_area AS JSON) FROM df_meta
"""

MATCH_INSERT = """
INSERT OR IGNORE INTO statsbomb_match
  (match_id, competition_id, season_id, match_date, kick_off, match_week,
   competition_stage_id, competition_stage, home_team_id, home_team,
   away_team_id, away_team, home_score, away_score, stadium_id, stadium,
   referee_id, referee)
SELECT match_id, competition_id, season_id, CAST(match_date AS DATE), kick_off,
   match_week, competition_stage_id, competition_stage, home_team_id, home_team,
   away_team_id, away_team, home_score, away_score, stadium_id, stadium,
   referee_id, referee
FROM df_m
"""


def ingest(tournament: str, apply: bool, limit: int | None) -> int:
    cid, sid = TOURNAMENTS[tournament]
    mode = "APPLY" if apply else "DRY-RUN"
    print("=" * 70)
    print(f"  StatsBomb ingest — {tournament} (comp={cid}, season={sid}) — {mode}")
    print("=" * 70)

    matches = sb.matches(competition_id=cid, season_id=sid)
    mdf = matches[[c for c in MATCH_COLS if c in matches.columns]].copy()
    print(f"  matches: {len(mdf)}")

    con = duckdb.connect(DB_PATH, read_only=not apply)
    try:
        if apply:
            _insert(con, mdf, MATCH_INSERT, "df_m")

        mids = mdf.sort_values("match_date")["match_id"].astype(int).tolist()
        if limit:
            mids = mids[:limit]
            print(f"  --limit {limit} -> {len(mids)} matches")

        tot_ev = tot_fr = tot_meta = tot_shots = 0
        no_360 = 0
        for n, mid in enumerate(mids, 1):
            ev_dict = sb.events(mid, fmt="dict")
            ev_rows = [parse_event(e, cid, sid) for e in ev_dict.values()]
            ev_df = pd.DataFrame(ev_rows)
            shots = int(ev_df["shot_xg"].notna().sum())
            if apply:
                _insert(con, ev_df, EVENT_INSERT, "df_ev")

            try:
                fr_list = sb.frames(mid, fmt="dict")
            except Exception:  # noqa: BLE001 - some matches lack 360
                fr_list = []
            if fr_list:
                fr_rows, meta_rows = parse_frames(fr_list, mid)
                if apply and fr_rows:
                    _insert(con, pd.DataFrame(fr_rows), FRAME_INSERT, "df_fr")
                    _insert(con, pd.DataFrame(meta_rows), META_INSERT, "df_meta")
                tot_fr += len(fr_rows); tot_meta += len(meta_rows)
            else:
                no_360 += 1

            tot_ev += len(ev_rows); tot_shots += shots
            print(f"   [{n}/{len(mids)}] match {mid}: "
                  f"{len(ev_rows)} ev, {shots} shots, "
                  f"{len(fr_list)} frame-events")

        print("\n" + "-" * 70)
        print(f"  TOTALS — events {tot_ev} | shots(w/ xG) {tot_shots} | "
              f"frame rows {tot_fr} | frame-meta {tot_meta} | "
              f"matches w/o 360: {no_360}")
        if apply:
            print("  APPLIED. Re-run (same args) to confirm idempotency (counts equal,"
                  " 0 new on a verify query).")
        else:
            print("  DRY-RUN — no writes. Cache warmed; re-run with --apply.")
        print("=" * 70)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tournament", required=True, choices=sorted(TOURNAMENTS))
    ap.add_argument("--apply", action="store_true",
                    help="execute writes (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap number of matches (quick check)")
    args = ap.parse_args()
    sys.exit(ingest(args.tournament, apply=args.apply, limit=args.limit))
