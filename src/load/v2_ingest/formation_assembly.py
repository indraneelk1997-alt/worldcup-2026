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

import duckdb

from src.load.v2_ingest.kernel_transforms import (
    AXES, DB_PATH, load_config, compute_forwardness, load_kernel,
    transform_kernel, _fmt_grid, _centroid_band, _centroid_lane,
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
                          "ea_id": ea_id, "mv_tags": [], "grid": None})
            continue
        a, d = load_kernel(con, pc, "attack"), load_kernel(con, pc, "defence")
        if not a or not d:
            raise SystemExit(f"no occupancy_base kernel for code {pc!r}")
        params, tags = ({"attack_band_extra": 0.0, "defence_band_extra": 0.0,
                         "spread": 0.0, "availability": 1.0}, [])
        if ea_id is not None:
            params, tags = player_movement_params(con, ea_id, cfg)
        grid = transform_kernel(a, d, axes, cfg["gains"], fwd[pc], fan_lane=fan, **params)
        slots.append({"slot_no": slot_no, "position_code": pc, "fan_lane": fan,
                      "ea_id": ea_id, "mv_tags": tags, "grid": grid})
    return axes, slots


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

    print(f"== {nation} / {formation} ==  gains={cfg['gains']} fan_step={cfg['fan_step']}")
    print("axes: " + ", ".join(f"{a}={axes[a]:.3f}" for a in AXES) + "\n")
    print(f"{'slot':>4} {'code':>5} {'player':>8} {'fan':>6} "
          f"{'band':>6} {'lane':>6} {'sum%':>6}  tags")
    show = []
    for s in slots:
        pid = str(s["ea_id"]) if s["ea_id"] else "-"
        tags = ",".join(s["mv_tags"])
        if s["grid"] is None:
            print(f"{s['slot_no']:>4} {s['position_code']:>5} {pid:>8} {'--':>6} "
                  f"{'(GK parked)':>20}")
            continue
        cb, cl, tot = _centroid_band(s["grid"]), _centroid_lane(s["grid"]), s["grid"].sum()
        print(f"{s['slot_no']:>4} {s['position_code']:>5} {pid:>8} {s['fan_lane']:>+6.2f} "
              f"{cb:>6.2f} {cl:>6.2f} {tot * 100:>6.1f}  {tags}")
        if s["fan_lane"] != 0.0 or s["mv_tags"]:   # show fanned or tweaked slots
            show.append(s)

    for s in show:
        print()
        title = (f"slot {s['slot_no']} {s['position_code']} "
                 f"(fan {s['fan_lane']:+.2f}; {','.join(s['mv_tags']) or 'no movement tags'}):")
        print(_fmt_grid(s["grid"], title))


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
