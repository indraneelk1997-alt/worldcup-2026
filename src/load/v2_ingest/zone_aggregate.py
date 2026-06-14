#!/usr/bin/env python3
"""
Item 8 -- zone aggregation (board sweep over the item-7 1v1 resolver).

This module orchestrates item-6 team boards + the item-7 zone battle into a
per-zone TEAM contest. Design: docs/item8_aggregation.md.

Built incrementally. This first cut delivers the pieces that need NO database,
so they can be validated standalone:

  * fold_zone(zone_id)   -- 30-zone board cell (band*5+lane) -> (authored zone
                            key, context). The mirror-fold + half-of-pitch
                            context selection (item-8 design A, "30->9 fold").
  * mirror_zone(zone_id) -- the opponent's board cell for the same physical
                            patch of grass (directional pairing).
  * the occupancy-weighted (Sum occ)^beta combine, exercised on a synthetic
    roster via `--demo` to prove the aggregation math behaves.

Deferred to the next step (needs real XIs on the board):
  * build_roster_from_board() -- load (player, occ) rosters from a real
    assembled team's team_boards() output, then sweep all 30 zones.

Run (no DB needed):
  uv run python src/load/v2_ingest/zone_aggregate.py --fold-table
  uv run python src/load/v2_ingest/zone_aggregate.py --demo
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Put the repo root on sys.path so the package-absolute imports used across
# v2_ingest (e.g. formation_assembly's `from src.load.v2_ingest...`) resolve
# whether this file is run as a plain script or as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.load.v2_ingest.zone_battle import (load_cfgs, resolve_context,
                                            load_player, find_squad, DB_PATH)

N_BANDS, N_LANES = 6, 5                       # board geometry (item-1 zone grid)

# Index -> authored-config token. The mirror fold collapses 6 bands -> 3 levels
# (B1<->B6, B2<->B5, B3<->B4) and 5 lanes -> 3 lane-types (LW==RW, LHS==RHS, C).
LEVELS = ["L1", "L2", "L3"]                    # min(band, 5-band): 0,1,2
LANE_TYPES = ["wing", "halfspace", "central"]  # min(lane, 4-lane): 0,1,2


def fold_zone(zone_id: int) -> tuple[str, str]:
    """Board cell 0..29 -> (authored zone key, context).

    Level   = min(band, 5-band)  -> L1 goal-adjacent .. L3 midfield.
    Lanetype= min(lane, 4-lane)  -> wing / halfspace / central.
    Context = which goal the cell is near, from the attack-oriented board:
              attacking half (band>=3) -> attack_vs_defense (chance contest);
              own half (band<3)        -> buildup_vs_pressure (play-out)."""
    band, lane = divmod(zone_id, N_LANES)
    level = LEVELS[min(band, (N_BANDS - 1) - band)]
    lanetype = LANE_TYPES[min(lane, (N_LANES - 1) - lane)]
    context = "attack_vs_defense" if band >= 3 else "buildup_vs_pressure"
    return f"{lanetype}_{level}", context


def mirror_zone(zone_id: int) -> int:
    """The opponent's board cell for the same physical patch of pitch. Both
    boards are stored attack-oriented (+band toward the goal each team attacks),
    so the opponent's view of a cell is the full point-reflection: band->5-band,
    lane->4-lane. Used to pair A's attack board against B's defence board."""
    band, lane = divmod(zone_id, N_LANES)
    return ((N_BANDS - 1) - band) * N_LANES + ((N_LANES - 1) - lane)


# --------------------------------------------------------------------------- #
# Validation harnesses (no DB)
# --------------------------------------------------------------------------- #

def _needed_attrs(ctx: dict) -> set:
    """Every attribute name the duels in this context reference, so a synthetic
    player can be given full coverage and never KeyError."""
    attrs = set()
    for stage in ("approach", "main"):
        for d in ctx[stage]:
            attrs |= set(d["att"]) | set(d["def"])
    return attrs


def _synth(name: str, needed: set, base: float, overrides: dict,
           fams: dict | None = None) -> dict:
    """A player dict shaped exactly like zone_battle.load_player() output:
    {name, attrs, fams}. attrs covers `needed`; `overrides` set the salient ones."""
    attrs = {a: base for a in needed}
    attrs.update(overrides)
    return {"name": name, "pos": "-", "nation": "-", "attrs": attrs,
            "fams": fams or {}}


def demo():
    """Prove the (Sum occ)^beta combine: hold quality fixed, vary NUMBERS, and
    show beta=1 lets overloads count while beta=0 ignores them."""
    battle, _ = load_cfgs()
    ctx = battle["zones"]["central_L1"]["attack_vs_defense"]
    gate, fmult = battle["approach_gate"], battle["family_mult"]
    needed = _needed_attrs(ctx)

    striker = _synth("Striker", needed, base=70, overrides={
        "finishing": 92, "positioning": 90, "composure": 88, "heading_accuracy": 84,
        "agility": 85, "balance": 80, "reactions": 88, "shot_power": 88, "volleys": 82})
    cb = _synth("CB", needed, base=70, overrides={
        "def_awareness": 88, "standing_tackle": 87, "sliding_tackle": 84,
        "interceptions": 86, "strength": 88, "jumping": 86, "aggression": 80,
        "heading_accuracy": 85, "reactions": 84})

    att = [(striker, 0.40)]
    one_def = [(cb, 0.40)]               # 1 defender
    two_def = [(cb, 0.40), (cb, 0.40)]   # 2 IDENTICAL defenders (pure numbers test)

    def run(att_r, def_r, beta):
        threat, ap, mn, *_ = resolve_context(att_r, def_r, ctx, gate, fmult, beta)
        occ_a = sum(o for _, o in att_r)
        occ_d = sum(o for _, o in def_r)
        return threat, ap, mn, occ_a, occ_d

    print("== central_L1 / attack_vs_defense -- synthetic numbers test ==\n")
    print("  Striker quality fixed; defenders are byte-identical clones.")
    print("  Only the COUNT of defenders changes.\n")
    print(f"  {'scenario':>22} {'Socc_att':>9} {'Socc_def':>9} {'approach':>9} "
          f"{'main':>7} {'THREAT':>7}")
    for label, def_r, beta in (
            ("1 def,  beta=1", one_def, 1.0),
            ("2 defs, beta=1", two_def, 1.0),
            ("1 def,  beta=0", one_def, 0.0),
            ("2 defs, beta=0", two_def, 0.0)):
        t, ap, mn, oa, od = run(att, def_r, beta)
        print(f"  {label:>22} {oa:>9.2f} {od:>9.2f} {ap:>9.3f} {mn:>7.3f} {t:>7.3f}")
    print("\n  Expect: beta=1 -> a 2nd identical defender LOWERS attacker threat")
    print("          (numbers count); beta=0 -> threat UNCHANGED (quality mean only).")


def fold_table():
    """Print the full 30->9 fold + context, and assert every folded key exists
    in the authored config (catches a naming mismatch between fold and JSON)."""
    battle, _ = load_cfgs()
    zones = battle["zones"]
    print("== 30-zone board -> authored zone / context fold ==\n")
    print(f"  {'zid':>3} {'band':>4} {'lane':>4}  {'zone_key':>14} {'context':>20} "
          f"{'mirror':>6}  {'in_cfg':>6}")
    missing = set()
    for zid in range(N_BANDS * N_LANES):
        band, lane = divmod(zid, N_LANES)
        key, ctx = fold_zone(zid)
        ok = key in zones
        if not ok:
            missing.add(key)
        print(f"  {zid:>3} {band:>4} {lane:>4}  {key:>14} {ctx:>20} "
              f"{mirror_zone(zid):>6}  {'yes' if ok else 'NO':>6}")
    if missing:
        print(f"\n  !! folded keys NOT in zone_battle.json: {sorted(missing)}")
    else:
        print("\n  all 30 cells fold to an authored zone key present in the config.")


# --------------------------------------------------------------------------- #
# Real-board sweep (needs DB): assemble two XIs, contest all 30 zones.
# --------------------------------------------------------------------------- #

# Hardcoded demo XIs (S36). slot_no -> name substring (resolved via name_norm
# LIKE). GK slot 1 omitted: GKs have no adjusted attrs / no outfield board.
ENG_XI = {2: "james", 3: "stones", 4: "guehi", 5: "burn", 6: "rice",
          7: "bellingham", 8: "henderson", 9: "saka", 10: "kane", 11: "rashford"}
NED_XI = {2: "dumfries", 3: "van dijk", 4: "nathan", 5: "van de ven", 6: "de roon",
          7: "de jong", 8: "reijnders", 9: "malen", 10: "gakpo", 11: "lang"}


def _resolve_xi(con, xi_names: dict, nation: str) -> tuple[dict, dict, dict]:
    """name-substring XI -> (xi_ea {slot:ea_id}, slot_to_sid {slot:squad_row_id},
    names {slot:player_name}). Scoped to `nation` (NOT find_squad, which is
    nation-agnostic and matched 'lang'->Elanga); requires adjusted attrs."""
    xi_ea, slot_to_sid, names = {}, {}, {}
    for slot_no, name in xi_names.items():
        r = con.execute(
            "SELECT s.squad_row_id, s.ea_id, s.player_name FROM wc2026_squad s "
            "JOIN player_adjusted_attributes_wide w ON w.squad_row_id=s.squad_row_id "
            "WHERE s.nation_code=? AND s.name_norm LIKE ? ORDER BY s.caps DESC LIMIT 1",
            [nation, f"%{name.lower()}%"]).fetchone()
        if not r:
            raise SystemExit(f"{nation}: no attr-player matching {name!r}")
        sid, ea, pname = r
        xi_ea[slot_no], slot_to_sid[slot_no], names[slot_no] = ea, sid, pname
    return xi_ea, slot_to_sid, names


def build_roster_from_board(con, board: dict, zone_id: int, slot_to_sid: dict,
                            p2f: dict, cache: dict) -> list:
    """One zone's [(player, occ)] roster from a team_boards() phase board.
    `weight` IS the occupancy. Players are cached (they recur across zones)."""
    roster = []
    for c in board.get(zone_id, []):
        sid = slot_to_sid.get(c["slot_no"])
        if sid is None:                       # unfilled slot (no player) -> skip
            continue
        if sid not in cache:
            cache[sid] = load_player(con, sid, p2f)
        roster.append((cache[sid], c["weight"]))
    return roster


def _fmt_grid(vals: dict, title: str, scale: float = 1.0, dec: int = 3):
    print(title)
    print("         lane0   lane1   lane2   lane3   lane4")
    for band in range(N_BANDS - 1, -1, -1):           # attacking end (B6) on top
        cells = []
        for lane in range(N_LANES):
            v = vals.get(band * N_LANES + lane)
            cells.append("   .  " if v is None else f"{v * scale:.{dec}f}")
        print(f"  B{band + 1}   " + "  ".join(f"{c:>6}" for c in cells))


def load_zone_xt(con) -> dict:
    """zone_id -> xt (attack-oriented positional value; B6-C peak ~0.143)."""
    return dict(con.execute("SELECT zone_id, xt FROM zone_xt").fetchall())


def demo_real():
    """Assemble ENG (attacking) vs NED (defending), both 4-3-3, and sweep all
    30 zones: ENG attack board @ Z  vs  NED defence board @ mirror(Z)."""
    import duckdb
    from src.load.v2_ingest.formation_assembly import (
        load_config, compute_forwardness, assemble, team_boards)
    battle, p2f = load_cfgs()
    gate, fmult = battle["approach_gate"], battle["family_mult"]
    beta = battle.get("aggregation_beta", 1.0)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    cfg, fwd = load_config(), compute_forwardness(con)

    eng_ea, eng_sid, eng_names = _resolve_xi(con, ENG_XI, "ENG")
    ned_ea, ned_sid, ned_names = _resolve_xi(con, NED_XI, "NED")
    print("  ENG XI:", ", ".join(eng_names[s] for s in sorted(eng_names)))
    print("  NED XI:", ", ".join(ned_names[s] for s in sorted(ned_names)), "\n")
    _, eng_slots = assemble(con, "4-3-3", "ENG", cfg, fwd, xi=eng_ea)
    _, ned_slots = assemble(con, "4-3-3", "NED", cfg, fwd, xi=ned_ea)
    eng_boards, ned_boards = team_boards(eng_slots), team_boards(ned_slots)

    cache = {}
    threats = {}
    for zid in range(N_BANDS * N_LANES):
        att = build_roster_from_board(con, eng_boards["attack"], zid, eng_sid, p2f, cache)
        dfn = build_roster_from_board(con, ned_boards["defence"], mirror_zone(zid),
                                      ned_sid, p2f, cache)
        if not att:                       # ENG has no attacking presence here
            threats[zid] = None
            continue                       # empty dfn flows -> uncontested (~1.0)
        key, ctx_name = fold_zone(zid)
        threat, *_ = resolve_context(att, dfn, battle["zones"][key][ctx_name],
                                     gate, fmult, beta)
        threats[zid] = threat

    print("== ENG (4-3-3, attacking) vs NED (4-3-3, defending) -- beta=%.1f ==\n" % beta)
    _fmt_grid(threats, "ENG control prob per zone -- P(win) (B6 = NED's box):")

    # --- step C: value-weight ---  value = entry_share * threat * zone_xt
    zxt = load_zone_xt(con)
    occ = {z: sum(c["weight"] for c in eng_boards["attack"].get(z, []))
           for z in range(N_BANDS * N_LANES)}
    occ_tot = sum(occ.values()) or 1.0           # ENG attack budget (~10.0)
    value, index = {}, 0.0
    for z in range(N_BANDS * N_LANES):
        t = threats.get(z)
        if t is None:
            value[z] = None
            continue
        value[z] = (occ[z] / occ_tot) * t * zxt[z]
        index += value[z]
    print()
    _fmt_grid(value, "ENG per-zone VALUE x1000 (entry_share x P(win) x zone_xt):",
              scale=1000.0, dec=3)
    print(f"\n  ENG attacking-value index (sum over zones) = {index:.5f}")
    print("  (per attacking SEQUENCE; still pre-conversion [step B] & pre-VOLUME [step D])")

    # detail: the central box (zid 27) vs a wing (zid 29) -- watch the flip
    for zid, label in ((27, "central_L1 box"), (29, "wing_L1")):
        key, ctx_name = fold_zone(zid)
        att = build_roster_from_board(con, eng_boards["attack"], zid, eng_sid, p2f, cache)
        dfn = build_roster_from_board(con, ned_boards["defence"], mirror_zone(zid),
                                      ned_sid, p2f, cache)
        print(f"\n  -- zid {zid} ({label}: {key}/{ctx_name}) --")
        print("     ENG att: " + (", ".join(f"{p['name'].split()[-1]}@{o:.2f}"
                                            for p, o in att) or "(empty)"))
        print("     NED def: " + (", ".join(f"{p['name'].split()[-1]}@{o:.2f}"
                                            for p, o in dfn) or "(empty)"))
        if att:
            t, ap, mn, *_ = resolve_context(att, dfn, battle["zones"][key][ctx_name],
                                            gate, fmult, beta)
            sa, sd = sum(o for _, o in att), sum(o for _, o in dfn)
            es = occ[zid] / occ_tot
            print(f"     Socc att={sa:.2f} def={sd:.2f}  P(win)={t:.3f}  |  "
                  f"zone_xt={zxt[zid]:.4f}  entry_share={es:.4f}  ->  "
                  f"VALUE={es * t * zxt[zid] * 1000:.3f} x1000")
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthetic numbers test")
    ap.add_argument("--fold-table", action="store_true", help="print 30->9 fold")
    ap.add_argument("--demo-real", action="store_true", help="ENG vs NED real sweep")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.fold_table:
        fold_table()
    elif a.demo_real:
        demo_real()
    else:
        print("try: --fold-table   or   --demo   or   --demo-real")


if __name__ == "__main__":
    main()
