#!/usr/bin/env python3
"""
Chessboard formation assembly -- compose a whole team's board.

Given a formation (from formation_slots) and a team (from team_playstyle_blended),
build the transformed occupancy kernel for each of the 11 slots:

    base kernels (occupancy_base)  ->  item-4 SHIFT (kernel_transforms)
                                   +   lateral-fan offset for duplicated central codes

Decision B (docs/item4_kernel_transforms.md): pure / lazy -- nothing persisted,
fired at assembly time. This module owns the XI loop + the fan rule; it imports
the pure transform from kernel_transforms. GK is parked (not in occupancy_base).

`--formation 4-2-3-1 --nation ESP` prints a per-slot summary + the fanned slots' grids.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict

import numpy as np
import duckdb

from src.load.v2_ingest.kernel_transforms import (
    AXES, DB_PATH, N_BANDS, N_LANES, load_config, compute_forwardness, load_kernel,
    transform_phase_grids, _fmt_grid, _centroid_band, _centroid_lane,
)

# central codes = home lane_pos 2.0 in position_home_cells.json. Only these
# fan when a formation fields N>1 of the SAME code; paired wide roles already
# carry distinct codes (LCB/RCB, LCM/RCM) so they never collide.
CENTRAL = {"GK", "CB", "DF", "DM", "MF", "CM", "CAM", "ST", "FW"}


def fan_offsets(n: int, step: float) -> list:
    """Symmetric lane offsets around the anchor for n copies of a code.
    n=2,step=1.0 -> [-0.5, +0.5] (lanes 1.5 & 2.5 for a central code)."""
    return [(i - (n - 1) / 2.0) * step for i in range(n)]


def player_movement_params(con, ea_id: int, cfg: dict) -> tuple:
    """Return (params, tags) for a player's Movement PlayStyles. params feeds
    transform_kernel's TWEAK kwargs; tags is a readable list for display.
    A player with no Movement tags -> neutral params (no kernel change)."""
    mt = cfg["movement_tweak"]
    rows = con.execute(
        "SELECT playstyle, tier FROM ea_fc26_playstyle WHERE ea_id=?", [ea_id]).fetchall()
    p = {"attack_band_extra": 0.0, "defence_band_extra": 0.0,
         "spread": 0.0, "availability": 1.0}
    tags = []
    for ps, tier in rows:
        spec = mt.get(ps)
        if not spec or ps.startswith("_"):
            continue
        v = spec["plus" if tier == "plus" else "base"]
        if spec["effect"] == "attack_band":
            p["attack_band_extra"] += v
        elif spec["effect"] == "defence_band":
            p["defence_band_extra"] += v
        elif spec["effect"] == "spread":
            p["spread"] += v
            p["availability"] += spec["avail_plus" if tier == "plus" else "avail_base"]
        tags.append(ps + ("+" if tier == "plus" else ""))
    return p, tags


def assemble(con, formation: str, nation: str, cfg: dict, fwd: dict,
             xi: dict | None = None) -> tuple:
    """Return (axes, slots) where slots is a list of dicts per slot_no:
    {slot_no, position_code, fan_lane, ea_id, mv_tags, grid (6x5 or None for GK)}.
    xi: optional {slot_no: ea_id}; slots with a player get the item-5 Movement
    TWEAK, slots without stay neutral (formation-only behaviour)."""
    xi = xi or {}
    row = con.execute(
        f"SELECT {', '.join(AXES)} FROM team_playstyle_blended WHERE nation_fifa3=?",
        [nation]).fetchone()
    if row is None:
        raise SystemExit(f"no team_playstyle_blended row for nation {nation!r}")
    axes = dict(zip(AXES, row))

    slots_raw = con.execute(
        "SELECT slot_no, position_code FROM formation_slots "
        "WHERE formation=? ORDER BY slot_no", [formation]).fetchall()
    if not slots_raw:
        raise SystemExit(f"no formation_slots for formation {formation!r}")

    counts = Counter(pc for _, pc in slots_raw)
    step = cfg["fan_step"]
    seen = defaultdict(int)
    slots = []
    for slot_no, pc in slots_raw:
        fan = 0.0
        if pc in CENTRAL and counts[pc] > 1:           # duplicated central code
            fan = fan_offsets(counts[pc], step)[seen[pc]]
            seen[pc] += 1
        ea_id = xi.get(slot_no)
        if pc == "GK":                                  # parked track, no kernel
            slots.append({"slot_no": slot_no, "position_code": pc, "fan_lane": 0.0,
                          "ea_id": ea_id, "mv_tags": [],
                          "attack_grid": None, "defence_grid": None})
            continue
        a, d = load_kernel(con, pc, "attack"), load_kernel(con, pc, "defence")
        if not a or not d:
            raise SystemExit(f"no occupancy_base kernel for code {pc!r}")
        params, tags = ({"attack_band_extra": 0.0, "defence_band_extra": 0.0,
                         "spread": 0.0, "availability": 1.0}, [])
        if ea_id is not None:
            params, tags = player_movement_params(con, ea_id, cfg)
        ga, gd = transform_phase_grids(a, d, axes, cfg["gains"], fwd[pc],
                                       fan_lane=fan, **params)
        slots.append({"slot_no": slot_no, "position_code": pc, "fan_lane": fan,
                      "ea_id": ea_id, "mv_tags": tags,
                      "attack_grid": ga, "defence_grid": gd})
    return axes, slots


def team_boards(slots, threshold: float = 0.0) -> dict:
    """Synthesis output (item 6, decision B): invert the per-slot phase grids
    into per-zone TEAM boards, kept phase-separate (possession blend deferred to
    item 8). Returns {'attack': board, 'defence': board} where board maps
    zone_id (band*5+lane) -> list of {slot_no, position_code, ea_id, weight}
    sorted desc. Per-slot grids stay the source of truth (item 7)."""
    boards = {"attack": defaultdict(list), "defence": defaultdict(list)}
    for s in slots:
        for phase, key in (("attack", "attack_grid"), ("defence", "defence_grid")):
            g = s.get(key)
            if g is None:                       # GK (parked)
                continue
            for b in range(N_BANDS):
                for l in range(N_LANES):
                    w = float(g[b, l])
                    if w > threshold:
                        boards[phase][b * N_LANES + l].append(
                            {"slot_no": s["slot_no"], "position_code": s["position_code"],
                             "ea_id": s["ea_id"], "weight": w})
    for phase in boards:
        for zid in boards[phase]:
            boards[phase][zid].sort(key=lambda c: -c["weight"])
    return {p: dict(boards[p]) for p in boards}


def _board_to_grid(board) -> np.ndarray:
    """Total team presence per zone (sum of all slots' contributions) -> 6x5."""
    grid = np.zeros((N_BANDS, N_LANES))
    for zid, contribs in board.items():
        grid[zid // N_LANES, zid % N_LANES] = sum(c["weight"] for c in contribs)
    return grid


def _demo_xi(con, formation: str) -> dict:
    """Auto-fill an XI from real EA data: drop a Rapid player into an attacking
    slot, a Relentless and a Press Proven player into midfield slots, so one run
    exercises all three Movement effects."""
    def find(tag):
        r = con.execute("SELECT ea_id FROM ea_fc26_playstyle WHERE playstyle=? "
                        "ORDER BY (tier='plus') DESC LIMIT 1", [tag]).fetchone()
        return r[0] if r else None
    slots_raw = con.execute("SELECT slot_no, position_code FROM formation_slots "
                            "WHERE formation=? ORDER BY slot_no", [formation]).fetchall()
    ATT = {"ST", "FW", "LW", "RW", "RAM", "LAM", "CAM"}
    MID = {"CM", "DM", "RCM", "LCM", "MF", "RM", "LM"}
    xi = {}
    for ea_id, group in ((find("Rapid"), ATT), (find("Relentless"), MID),
                         (find("Press Proven"), MID)):
        if not ea_id:
            continue
        for slot_no, pc in slots_raw:
            if pc in group and slot_no not in xi:
                xi[slot_no] = ea_id
                break
    return xi


def probe(formation: str, nation: str, xi_spec: str = "", demo: bool = False):
    cfg = load_config()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    fwd = compute_forwardness(con)
    if demo:
        xi = _demo_xi(con, formation)
    elif xi_spec:
        xi = {int(s.split(":")[0]): int(s.split(":")[1]) for s in xi_spec.split(",")}
    else:
        xi = {}
    axes, slots = assemble(con, formation, nation, cfg, fwd, xi=xi)
    boards = team_boards(slots)

    print(f"== {nation} / {formation} ==  gains={cfg['gains']} fan_step={cfg['fan_step']}")
    print("axes: " + ", ".join(f"{a}={axes[a]:.3f}" for a in AXES) + "\n")

    # per-slot summary: attack-phase + defence-phase centroids (band/lane)
    print(f"{'slot':>4} {'code':>5} {'player':>8} {'fan':>6} "
          f"{'ATK b/l':>13} {'DEF b/l':>13}  tags")
    for s in slots:
        pid = str(s["ea_id"]) if s["ea_id"] else "-"
        if s["attack_grid"] is None:
            print(f"{s['slot_no']:>4} {s['position_code']:>5} {pid:>8} {'--':>6}   (GK parked)")
            continue
        ab, al = _centroid_band(s["attack_grid"]), _centroid_lane(s["attack_grid"])
        db, dl = _centroid_band(s["defence_grid"]), _centroid_lane(s["defence_grid"])
        print(f"{s['slot_no']:>4} {s['position_code']:>5} {pid:>8} {s['fan_lane']:>+6.2f} "
              f"{ab:>5.2f}/{al:<6.2f} {db:>5.2f}/{dl:<6.2f}  {','.join(s['mv_tags'])}")

    # synthesis: the two per-zone team boards (zone-total presence)
    for phase in ("attack", "defence"):
        print()
        print(_fmt_grid(_board_to_grid(boards[phase]),
                        f"TEAM {phase.upper()} board (zone-total presence %; sum=team budget):"))
        zid = max(boards[phase], key=lambda z: sum(c["weight"] for c in boards[phase][z]))
        b, l = zid // N_LANES, zid % N_LANES
        who = ", ".join(f"{c['position_code']}{('#' + str(c['slot_no']))}={c['weight'] * 100:.0f}%"
                        for c in boards[phase][zid][:4])
        print(f"  busiest zone B{b + 1}/lane{l}: {who}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formation", default="4-2-3-1")
    ap.add_argument("--nation", default="ESP")
    ap.add_argument("--demo", action="store_true", help="auto-fill real movers")
    ap.add_argument("--xi", default="", help='explicit "slot:ea_id,slot:ea_id"')
    a = ap.parse_args()
    probe(a.formation, a.nation, xi_spec=a.xi, demo=a.demo)


if __name__ == "__main__":
    main()
