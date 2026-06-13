#!/usr/bin/env python3
"""
Item 7 -- zone battle resolution (Central-L1 first; build 1 zone at a time).

A zone contest is a sequence of opposed micro-duels in two stages (approach,
main). Each duel -> a Bradley-Terry win-prob on the two sides' weighted attribute
scores; a stage = weighted mean of its duels; threat = main*(g + (1-g)*approach).
EA PlayStyle families modestly multiply the attrs in the duels they touch.

Design: docs/item7_zone_battle.md. Inputs: player_adjusted_attributes_wide (S29)
+ wc2026_squad (squad_row_id<->ea_id) + ea_fc26_playstyle + playstyle_families.json.

This is the 1v1 core (occupancy-weighted aggregation over a zone is the next step).
`--probe --attacker Kane --defender "Van Dijk"` resolves Central-L1.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
DB_PATH = REPO / "data" / "processed" / "worldcup.duckdb"
BATTLE_CFG = REPO / "data" / "config" / "zone_battle.json"
FAMILIES_CFG = REPO / "data" / "config" / "playstyle_families.json"


def load_cfgs():
    battle = json.loads(BATTLE_CFG.read_text())
    p2f = json.loads(FAMILIES_CFG.read_text())["playstyle_to_family"]
    return battle, p2f


def find_squad(con, q: str) -> int:
    """Resolve a squad_row_id from an int string or a name substring (name_norm
    is accent/space-stripped, so 'mbappe' matches). Must have adjusted attrs."""
    if q.isdigit():
        return int(q)
    r = con.execute(
        "SELECT s.squad_row_id, s.player_name FROM wc2026_squad s "
        "JOIN player_adjusted_attributes_wide w ON w.squad_row_id = s.squad_row_id "
        "WHERE s.name_norm LIKE ? ORDER BY s.caps DESC LIMIT 1",
        [f"%{q.lower()}%"]).fetchone()
    if not r:
        raise SystemExit(f"no squad player with adjusted attrs matching {q!r}")
    return r[0]


def load_player(con, sid: int, p2f: dict) -> dict:
    w = con.execute("SELECT * FROM player_adjusted_attributes_wide WHERE squad_row_id=?",
                    [sid]).fetchone()
    if w is None:
        raise SystemExit(f"no adjusted attrs for squad_row_id {sid}")
    attrs = dict(zip([d[0] for d in con.description], w))
    name, nation, pos, ea_id = con.execute(
        "SELECT player_name, nation_code, position_class, ea_id FROM wc2026_squad "
        "WHERE squad_row_id=?", [sid]).fetchone()
    fams = {}                                   # family -> 'base'/'plus' (best tier)
    if ea_id is not None:
        for ps, tier in con.execute(
                "SELECT playstyle, tier FROM ea_fc26_playstyle WHERE ea_id=?",
                [ea_id]).fetchall():
            fam = p2f.get(ps)
            if fam and fams.get(fam) != "plus":    # 'plus' wins over 'base'
                fams[fam] = tier
    return {"sid": sid, "name": name, "nation": nation, "pos": pos,
            "attrs": attrs, "fams": fams}


def _family_mult(player: dict, boost_families: list, fmult: dict) -> float:
    best = 1.0
    for fam in boost_families:
        if fam in player["fams"]:
            best = max(best, fmult[player["fams"][fam]])
    return best


def _side_score(player: dict, attr_w: dict, boost: list, fmult: dict) -> float:
    m = _family_mult(player, boost, fmult)
    return sum(w * player["attrs"][a] * m for a, w in attr_w.items())


def _bt(a: float, d: float) -> float:
    return a / (a + d) if (a + d) > 0 else 0.5


def resolve_stage(att, dfn, duels, fmult):
    tot_w = sum(d["w"] for d in duels)
    p, rows = 0.0, []
    for d in duels:
        a = _side_score(att, d["att"], d.get("att_boost", []), fmult)
        v = _side_score(dfn, d["def"], d.get("def_boost", []), fmult)
        pd = _bt(a, v)
        p += d["w"] * pd
        rows.append((d["name"], d["w"], a, v, pd))
    return p / tot_w, rows


def resolve_context(att, dfn, ctx, gate, fmult):
    ap, ap_rows = resolve_stage(att, dfn, ctx["approach"], fmult)
    mn, mn_rows = resolve_stage(att, dfn, ctx["main"], fmult)
    threat = mn * (gate + (1.0 - gate) * ap)
    return threat, ap, mn, ap_rows, mn_rows


def probe(attacker: str, defender: str, zone: str, context: str):
    battle, p2f = load_cfgs()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    att = load_player(con, find_squad(con, attacker), p2f)
    dfn = load_player(con, find_squad(con, defender), p2f)
    ctx = battle["zones"][zone][context]
    gate, fmult = battle["approach_gate"], battle["family_mult"]
    threat, ap, mn, ap_rows, mn_rows = resolve_context(att, dfn, ctx, gate, fmult)

    print(f"== {zone} / {context} ==  approach_gate={gate}")
    print(f"  ATT  {att['name']} ({att['nation']}, {att['pos']})  "
          f"fams={att['fams'] or '-'}")
    print(f"  DEF  {dfn['name']} ({dfn['nation']}, {dfn['pos']})  "
          f"fams={dfn['fams'] or '-'}\n")
    for stage, rows in (("APPROACH", ap_rows), ("MAIN", mn_rows)):
        print(f"  {stage}")
        print(f"    {'duel':>14} {'w':>5} {'att':>7} {'def':>7} {'p(att)':>7}")
        for name, w, a, v, pd in rows:
            print(f"    {name:>14} {w:>5.2f} {a:>7.1f} {v:>7.1f} {pd:>7.3f}")
    print(f"\n  approach={ap:.3f}  main={mn:.3f}  ->  THREAT(att prevails)={threat:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--attacker", default="Kane")
    ap.add_argument("--defender", default="Van Dijk")
    ap.add_argument("--zone", default="central_L1")
    ap.add_argument("--context", default="attack_vs_defense",
                    choices=["attack_vs_defense", "buildup_vs_pressure"])
    a = ap.parse_args()
    if a.probe:
        probe(a.attacker, a.defender, a.zone, a.context)
    else:
        print("try: --probe --attacker Kane --defender 'Van Dijk'")


if __name__ == "__main__":
    main()
