"""Read-only review list: Understat-relink candidates for squad outfielders whose
Understat (attack/possession) link currently FAILS (att_min=0 in the blend engine).

The engine (`_probe_adjusted_ratings.build`) matches Understat by HARDENED NAME,
which breaks on variants — `mbappe` vs `mbappe-lottin`, word order (`hwang
hee-chan` vs `hee-chan hwang`), middle names (`jonathan christian david`). Understat
rows carry NO nation/dob, so CLUB is the key corroborator: squad.club vs the
Understat player's team(s). Composite = club_sim + token-aware name_sim.

Two guards against the mononym collisions we saw (one 'danilo' / 'kevin' / 'pedro'
matching several squad players):
  1. an auto-suggest REQUIRES club corroboration (club_sim >= CLUB_MIN);
  2. any Understat id auto-suggested for >1 squad row is dropped to review.

Writes understat_relink_review.csv + data/config/understat_id_overrides.proposed.json.
NO DB writes.

Run:  uv run python src/load/v2_ingest/_probe_understat_relink.py
"""
from __future__ import annotations
import csv
import difflib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pandas as pd

import _probe_adjusted_ratings as eng          # the canonical blend engine (att_min)

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "processed" / "worldcup.duckdb"
OUT = ROOT / "understat_relink_review.csv"
PROPOSED = ROOT / "data" / "config" / "understat_id_overrides.proposed.json"
TOPN = 5
W_CLUB, W_NAME = 0.55, 0.45     # club dominates (the only corroborator we have here)
STRONG = 0.78                   # composite >= this AND club corroborated -> auto-suggest
CLUB_MIN = 0.60                 # club_sim floor for an auto-suggest
NAME_FLOOR = 0.45               # cheap candidate prefilter
_CLUB_STOP = (" fc", " cf", " sc", " ac", " afc", " cd", " sad", " club", " calcio")


def _deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _tokens(s) -> list[str]:
    if not isinstance(s, str):
        return []
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", _deacc(s).lower()).split() if t]


def _normclub(s) -> str:
    if not isinstance(s, str):
        return ""
    c = re.sub(r"[^a-z0-9 ]", " ", _deacc(s).lower())
    for t in _CLUB_STOP:
        c = c.replace(t, " ")
    return re.sub(r"\s+", " ", c).strip()


def _tok_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _aslist(ts) -> list:
    """DuckDB list(DISTINCT ...) -> numpy array; coerce to a clean Python list."""
    if ts is None:
        return []
    try:
        return [t for t in ts if t is not None]
    except TypeError:
        return []


def _name_sim(qt: list[str], ct: list[str]) -> float:
    if not qt or not ct:
        return 0.0
    fwd = sum(max(_tok_sim(a, b) for b in ct) for a in qt) / len(qt)
    rev = sum(max(_tok_sim(b, a) for a in qt) for b in ct) / len(ct)
    return (fwd + rev) / 2.0


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)

    # 1. squad outfielders the engine currently fails to link to Understat
    bf = eng.build(con)
    miss = set(bf.loc[(bf["grp"] != "GK") & (bf["att_min"] == 0),
                      "squad_row_id"].astype(int))
    sq = con.execute("SELECT squad_row_id, nation_code, player_name, club "
                     "FROM wc2026_squad").df()
    sq = sq[sq["squad_row_id"].isin(miss)].copy()

    # 2. Understat universe: one row per Understat player_id, with team(s) + minutes
    us = con.execute("""
        SELECT pl.player_id, pl.player_name,
               list(DISTINCT p.team) AS teams, sum(p.minutes) AS mins, count(*) AS games
        FROM player_match_stats p JOIN players pl ON p.player_id = pl.player_id
        GROUP BY 1, 2""").df()
    con.close()
    us = us[us["mins"] > 0].copy()
    us["tok"] = us["player_name"].map(_tokens)
    us["nclubs"] = us["teams"].map(lambda ts: [_normclub(t) for t in _aslist(ts)])

    # token block: token -> list of Understat rows (so we only score plausible cands)
    by_tok: dict[str, list] = defaultdict(list)
    for c in us.itertuples():
        for t in set(c.tok):
            by_tok[t].append(c)

    rows = []
    for r in sq.itertuples():
        qtok, qclub = _tokens(r.player_name), _normclub(r.club)
        cands = {}
        for t in set(qtok):
            for c in by_tok.get(t, []):
                cands[c.player_id] = c
        scored = []
        for c in cands.values():
            nsim = _name_sim(qtok, c.tok)
            if nsim < NAME_FLOOR:
                continue
            csim = max((difflib.SequenceMatcher(None, qclub, nc).ratio()
                        for nc in c.nclubs), default=0.0) if qclub else 0.0
            comp = W_CLUB * csim + W_NAME * nsim
            scored.append((comp, csim, nsim, c))
        scored.sort(key=lambda t: t[0], reverse=True)
        for rank, (comp, csim, nsim, c) in enumerate(scored[:TOPN], 1):
            rows.append({
                "squad_row_id": int(r.squad_row_id), "nation": r.nation_code,
                "squad_name": r.player_name, "squad_club": r.club, "rank": rank,
                "cand_understat_id": int(c.player_id), "cand_name": c.player_name,
                "cand_teams": "; ".join(_aslist(c.teams)), "cand_mins": int(c.mins),
                "cand_games": int(c.games),
                "composite": round(comp, 3), "club_sim": round(csim, 2),
                "name_sim": round(nsim, 2),
                "suggest": "y" if (rank == 1 and comp >= STRONG and csim >= CLUB_MIN) else "",
                "confirm": "",
            })

    # guard 2: drop any Understat id auto-suggested for >1 squad row (ambiguous)
    sug = Counter(x["cand_understat_id"] for x in rows if x["suggest"] == "y")
    for x in rows:
        if x["suggest"] == "y" and sug[x["cand_understat_id"]] > 1:
            x["suggest"] = ""

    if rows:
        with OUT.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    proposed = {"_comment": (
        "Proposed Understat relinks (auto: rank-1, composite>=%.2f, club_sim>=%.2f, "
        "club not ambiguous). VERIFY then rename to understat_id_overrides.json. "
        "Drop wrong rows; add manual picks from understat_relink_review.csv "
        "(set understat_player_id + src='manual')." % (STRONG, CLUB_MIN))}
    for x in rows:
        if x["suggest"] == "y":
            proposed[str(x["squad_row_id"])] = {
                "understat_player_id": x["cand_understat_id"], "squad": x["squad_name"],
                "understat": x["cand_name"], "teams": x["cand_teams"],
                "mins": x["cand_mins"], "composite": x["composite"], "src": "auto"}
    PROPOSED.write_text(json.dumps(proposed, indent=2, ensure_ascii=False), "utf-8")

    n_sug = sum(1 for x in rows if x["suggest"] == "y")
    n_players = len({x["squad_row_id"] for x in rows})
    print(f"missing-Understat outfielders: {len(miss)}  "
          f"(with >=1 token candidate: {n_players})")
    print(f"-> wrote {OUT.name} ({len(rows)} rows, top {TOPN}/player)")
    print(f"-> wrote {PROPOSED.name} ({n_sug} auto-suggested, club-corroborated, unambiguous)\n")
    print("== auto-suggested relinks (eyeball squad -> Understat) ==")
    for x in sorted((r for r in rows if r["suggest"] == "y"),
                    key=lambda v: -v["composite"]):
        print(f"  {x['nation']} {x['squad_name']!r}/{x['squad_club']!r} -> "
              f"{x['cand_name']!r}/{x['cand_teams']!r} "
              f"(id {x['cand_understat_id']}, {x['cand_mins']}min, comp {x['composite']}, "
              f"club {x['club_sim']}, name {x['name_sim']})")
    # strong name match but NOT auto-suggested (club gap / ambiguous) — manual review
    near = [x for x in rows if x["rank"] == 1 and x["suggest"] == "" and x["name_sim"] >= 0.8]
    print(f"\n== strong name, NO auto-suggest (verify by hand: club differs or ambiguous) "
          f"({len(near)}) ==")
    for x in sorted(near, key=lambda v: -v["name_sim"])[:25]:
        print(f"  {x['nation']} {x['squad_name']!r}/{x['squad_club']!r} -> "
              f"{x['cand_name']!r}/{x['cand_teams']!r} "
              f"(name {x['name_sim']}, club {x['club_sim']})")


if __name__ == "__main__":
    main()
