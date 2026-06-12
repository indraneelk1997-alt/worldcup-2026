"""
S27 — derive per-player-per-match MINUTES for StatsBomb (the per-90 prerequisite).

StatsBomb events carry no `minutes` column (unlike Understat/FBref). We derive
it from observed event structure (S27, match 3930158):
  * minute = cumulative match clock incl. stoppage (P1 0-48, P2 45-93) and ET
    just adds periods 3/4 → match_end = global max(minute). No special ET logic.
  * Starting XI events (2/match) → raw.tactics.lineup = 11 starters (start=0).
  * Substitution events → event `player` = OFF (at `minute`);
    raw.substitution.replacement = ON (start = that minute).
  * Foul Committed / Bad Behaviour with card in {Red Card, Second Yellow}
    → that player's exit caps at the card minute.

minutes = end − start;  start = 0 if starter else sub-on min;
end = min(own sub-off, own red, match_end).

Output = NEW derived table `statsbomb_player_match` (match × player grain) — the
StatsBomb analog of player_match_stats / player_match_fbref. It is DERIVED, so
--apply rebuilds it wholesale (CREATE OR REPLACE) — safe, not a source layer.

Default DRY-RUN prints the GER-SCO (3930158) breakdown for hand-validation +
sanity stats; --apply writes the table.

    uv run python src/load/v2_ingest/derive_statsbomb_minutes.py            # dry-run
    uv run python src/load/v2_ingest/derive_statsbomb_minutes.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import sys

import duckdb
import pandas as pd

DB_PATH = "data/processed/worldcup.duckdb"
SENDOFF_CARDS = {"Red Card", "Second Yellow"}


def derive(con) -> pd.DataFrame:
    # match end = max clock minute over PLAYING periods only (1-4: reg + ET).
    # Period 5 = penalty shootout — NOT playing time, excluded.
    ends = dict(con.sql(
        "SELECT match_id, max(minute) FROM statsbomb_event "
        "WHERE period <= 4 GROUP BY 1").fetchall())
    meta = {r[0]: (r[1], r[2]) for r in con.sql(
        "SELECT match_id, competition_id, season_id FROM statsbomb_match").fetchall()}

    sx = con.sql("SELECT match_id, team, team_id, raw FROM statsbomb_event "
                 "WHERE type='Starting XI'").fetchall()
    subs = con.sql("SELECT match_id, minute, player_id, team, team_id, raw "
                   "FROM statsbomb_event WHERE type='Substitution'").fetchall()
    cards = con.sql("SELECT match_id, minute, player_id, raw FROM statsbomb_event "
                    "WHERE type IN ('Foul Committed','Bad Behaviour')").fetchall()

    # per-match scratch
    starters: dict = {}   # match -> {pid: (name, team, team_id)}
    sub_on: dict = {}     # match -> {pid: (minute, name, team, team_id)}
    sub_off: dict = {}    # match -> {pid: minute}
    reds: dict = {}       # match -> {pid: minute}

    for mid, team, team_id, raw in sx:
        d = starters.setdefault(mid, {})
        for e in json.loads(raw)["tactics"]["lineup"]:
            d[e["player"]["id"]] = (e["player"]["name"], team, team_id)

    for mid, minute, pid, team, team_id, raw in subs:
        sub_off.setdefault(mid, {})[pid] = minute            # event player = OFF
        rep = json.loads(raw).get("substitution", {}).get("replacement", {})
        if rep:
            sub_on.setdefault(mid, {})[rep["id"]] = (minute, rep.get("name"),
                                                     team, team_id)

    for mid, minute, pid, raw in cards:
        rj = json.loads(raw)
        card = (rj.get("foul_committed", {}) or {}).get("card", {}) \
            or (rj.get("bad_behaviour", {}) or {}).get("card", {})
        if card.get("name") in SENDOFF_CARDS:
            # earliest sending-off if somehow multiple
            cur = reds.setdefault(mid, {}).get(pid)
            reds[mid][pid] = min(minute, cur) if cur is not None else minute

    rows = []
    for mid in starters:
        end_m = ends.get(mid, 90)
        cid, sid = meta.get(mid, (None, None))
        roster = set(starters[mid]) | set(sub_on.get(mid, {}))
        for pid in roster:
            is_start = pid in starters[mid]
            if is_start:
                on = 0
                name, team, team_id = starters[mid][pid]
            else:
                on, name, team, team_id = sub_on[mid][pid]
            offs = [end_m]
            if pid in sub_off.get(mid, {}):
                offs.append(sub_off[mid][pid])
            if pid in reds.get(mid, {}):
                offs.append(reds[mid][pid])
            off = min(offs)
            rows.append({
                "match_id": mid, "player_id": pid, "player": name,
                "team": team, "team_id": team_id, "competition_id": cid,
                "season_id": sid, "started": is_start, "on_min": int(on),
                "off_min": int(off), "minutes": max(int(off) - int(on), 0),
            })
    return pd.DataFrame(rows)


def main(apply: bool) -> int:
    con = duckdb.connect(DB_PATH, read_only=not apply)
    df = derive(con)

    print("=" * 66)
    print(f"  StatsBomb minutes derivation — {'APPLY' if apply else 'DRY-RUN'}")
    print("=" * 66)
    print(f"player-match rows: {len(df)}  |  matches: {df['match_id'].nunique()}  "
          f"|  players: {df['player_id'].nunique()}")
    print("minutes distribution:", df["minutes"].describe()[
        ["min", "25%", "50%", "75%", "max"]].round(1).to_dict())
    print("  minutes > 130 (should be ~0; ET caps ~120+stoppage):",
          int((df["minutes"] > 130).sum()))
    print("  minutes <= 0 (should be 0):", int((df["minutes"] <= 0).sum()))
    print("  max period in data:", con.sql("SELECT max(period) FROM statsbomb_event").fetchone()[0],
          "| matches with shootout (period>=5):",
          con.sql("SELECT count(DISTINCT match_id) FROM statsbomb_event WHERE period>=5").fetchone()[0])

    print("\n=== HAND-VALIDATION: match 3930158 (GER 5-1 SCO) ===")
    v = df[df["match_id"] == 3930158].sort_values(["team", "minutes"])
    for r in v.itertuples():
        flag = "" if r.started else "  (sub)"
        print(f"  {r.team:9} {r.player:28} {r.on_min:3}->{r.off_min:3} "
              f"= {r.minutes:3}'{flag}")
    print("  expect: Ryan Porteous 0->41 = 41 (red); full starters ->93; "
          "HT subs off=45, on=48.")

    if apply:
        con.register("sbpm", df)
        con.execute("CREATE OR REPLACE TABLE statsbomb_player_match AS "
                    "SELECT * FROM sbpm")
        con.execute("SELECT count(*) FROM statsbomb_player_match")
        con.unregister("sbpm")
        print("\nAPPLIED -> statsbomb_player_match (derived; rebuilt wholesale).")
    else:
        print("\nDRY-RUN — no writes. Validate the match above, then --apply.")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    args = ap.parse_args()
    sys.exit(main(apply=args.apply))
