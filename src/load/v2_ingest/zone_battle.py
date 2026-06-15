#!/usr/bin/env python3
"""
Item 7 -- zone battle resolution (Central-L1 first; build 1 zone at a time).

A zone contest is a sequence of opposed micro-duels in two stages (approach,
main). Each duel -> a Bradley-Terry win-prob on the two sides' weighted attribute
scores; a stage = weighted mean of its duels; threat = main*(g + (1-g)*approach).
EA PlayStyle families modestly multiply the attrs in the duels they touch.

Design: docs/item7_zone_battle.md. Inputs: player_adjusted_attributes_wide (S29)
+ wc2026_squad (squad_row_id<->ea_id) + ea_fc26_playstyle + playstyle_families.json.

The resolver now takes per-side player rosters [(player, occ), ...] and combines
them with the item-8 occupancy-weighted (Σocc)^beta sum (_team_side_score). The
1v1 `--probe` passes a single-player roster at occ=1.0 -> reduces to the old
_side_score exactly (regression-safe). Board sweep over a real zone is the next step.
`--probe --attacker Kane --defender "Van Dijk"` resolves Central-L1.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
# DB path is env-overridable via WC2026_DB so the dashboard (or a friend running
# a trimmed runtime DB) can point elsewhere without editing code. Default = the
# full local DB, so all existing scripts/behaviour are unchanged.
DB_PATH = Path(os.environ.get("WC2026_DB",
                              REPO / "data" / "processed" / "worldcup.duckdb"))
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
    # weighted MEAN of the relevant attrs (sum-invariant: only weight RATIOS
    # matter, so attr weights need not sum to 1 and a typo can't bias a duel).
    m = _family_mult(player, boost, fmult)
    tot = sum(attr_w.values())
    if tot == 0:
        return 0.0
    return m * sum(w * player["attrs"][a] for a, w in attr_w.items()) / tot


def _team_side_score(players: list, attr_w: dict, boost: list,
                     fmult: dict, beta: float) -> float:
    """Occupancy-weighted combine over every player present in the zone
    (item-8 design A). `players` = list of (player_dict, occ).

        side = (Σ occ)^beta · [ Σ occ·q / Σ occ ]
               └ numbers ┘      └ occ-weighted mean quality ┘
        q = per-player _side_score (quality, incl. that player's family_mult).

    beta=1 -> the item-7 doc's literal Σ occ·q sum (overloads count linearly);
    beta=0 -> pure quality mean (numbers discarded). Default beta=1.
    The 1v1 case [(p, 1.0)] reduces to _side_score(p) exactly -> regression-safe."""
    occ_tot = sum(occ for _, occ in players)
    if occ_tot <= 0:
        return 0.0
    wq = sum(occ * _side_score(p, attr_w, boost, fmult) for p, occ in players)
    return (occ_tot ** beta) * (wq / occ_tot)


def _bt(a: float, d: float) -> float:
    return a / (a + d) if (a + d) > 0 else 0.5


def resolve_stage(att_players, dfn_players, duels, fmult, beta):
    # att_players / dfn_players: list of (player_dict, occ). The 1v1 caller
    # passes [(player, 1.0)]; the board sweep (next step) passes the zone roster.
    tot_w = sum(d["w"] for d in duels)
    p, rows = 0.0, []
    for d in duels:
        a = _team_side_score(att_players, d["att"], d.get("att_boost", []), fmult, beta)
        v = _team_side_score(dfn_players, d["def"], d.get("def_boost", []), fmult, beta)
        pd = _bt(a, v)
        p += d["w"] * pd
        rows.append((d["name"], d["w"], a, v, pd))
    return p / tot_w, rows


def resolve_context(att_players, dfn_players, ctx, gate, fmult, beta=1.0):
    ap, ap_rows = resolve_stage(att_players, dfn_players, ctx["approach"], fmult, beta)
    mn, mn_rows = resolve_stage(att_players, dfn_players, ctx["main"], fmult, beta)
    threat = mn * (gate + (1.0 - gate) * ap)
    return threat, ap, mn, ap_rows, mn_rows


def probe(attacker: str, defender: str, zone: str, context: str):
    battle, p2f = load_cfgs()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    att = load_player(con, find_squad(con, attacker), p2f)
    dfn = load_player(con, find_squad(con, defender), p2f)
    ctx = battle["zones"][zone][context]
    gate, fmult = battle["approach_gate"], battle["family_mult"]
    beta = battle.get("aggregation_beta", 1.0)          # safe default if key absent
    att_players, dfn_players = [(att, 1.0)], [(dfn, 1.0)]   # 1v1 = degenerate board
    threat, ap, mn, ap_rows, mn_rows = resolve_context(
        att_players, dfn_players, ctx, gate, fmult, beta)

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
