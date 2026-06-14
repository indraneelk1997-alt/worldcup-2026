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

from src.load.v2_ingest.zone_battle import (load_cfgs, resolve_context, load_player,
                                            find_squad, _team_side_score, DB_PATH)

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


# slot position_code -> coarse group (matches wc2026_squad.primary_position_group;
# S27: wingers/CAM -> FWD, pivots -> MID).
SLOT_GROUP = {
    "GK": "GK",
    "RB": "DEF", "RCB": "DEF", "CB": "DEF", "LCB": "DEF", "LB": "DEF",
    "RWB": "DEF", "LWB": "DEF",
    "DM": "MID", "CM": "MID", "RCM": "MID", "LCM": "MID", "RM": "MID", "LM": "MID",
    "CAM": "FWD", "RW": "FWD", "LW": "FWD", "ST": "FWD", "FW": "FWD",
    "RAM": "FWD", "LAM": "FWD",
}


def selection_scores(con, quality_w: float = 0.6) -> dict:
    """squad_row_id -> selection score = quality_w * adjusted-role-rating(pct) +
    (1-quality_w) * caps(pct within group). Quality is the empirical-adjusted role
    rating (build()): DEF->Defense, FWD->Attack, MID->two-way(Possession+Defense).
    Computed ONCE; young stars score high since thin-minutes adj ~= EA percentile."""
    import numpy as np
    from src.load.v2_ingest._probe_adjusted_ratings import build
    df = build(con)[["squad_row_id", "grp", "adj_Attack", "adj_Possession",
                     "adj_Defense"]].copy()
    caps = dict(con.execute("SELECT squad_row_id, caps FROM wc2026_squad").fetchall())
    df["caps"] = df["squad_row_id"].map(caps).fillna(0)
    df["quality"] = np.select(
        [df.grp == "DEF", df.grp == "FWD"],
        [df.adj_Defense, df.adj_Attack],
        default=0.5 * (df.adj_Possession + df.adj_Defense))
    df["caps_pct"] = df.groupby("grp")["caps"].rank(pct=True) * 100
    df["quality"] = df["quality"].fillna(df["caps_pct"])      # no adj -> lean on caps
    df["score"] = quality_w * df["quality"] + (1 - quality_w) * df["caps_pct"]
    return dict(zip(df["squad_row_id"], df["score"]))


def autopick_xi(con, nation: str, formation: str = "4-3-3",
                scores: dict | None = None) -> tuple[dict, dict, dict]:
    """Greedy best-XI: each outfield slot -> top unused player in the slot's group by
    `scores` (selection_scores: quality x caps blend), else raw caps. GK slot left
    unfilled (parked board; GK handled separately for conversion). Falls back to any
    remaining player if a group runs short.
    -> (xi_ea {slot:ea_id}, slot_to_sid {slot:squad_row_id}, names {slot:name})."""
    slots = con.execute(
        "SELECT slot_no, position_code FROM formation_slots WHERE formation=? "
        "ORDER BY slot_no", [formation]).fetchall()
    rows = con.execute(
        "SELECT s.squad_row_id, s.ea_id, s.player_name, s.primary_position_group, s.caps "
        "FROM wc2026_squad s JOIN player_adjusted_attributes_wide w "
        "ON w.squad_row_id = s.squad_row_id "
        "WHERE s.nation_code=? AND s.primary_position_group IN ('DEF','MID','FWD')",
        [nation]).fetchall()
    key = (lambda r: scores.get(r[0], 0.0)) if scores else (lambda r: r[4] or 0)
    rows = sorted(rows, key=key, reverse=True)
    pools = {"DEF": [], "MID": [], "FWD": []}
    for sid, ea, name, grp, _caps in rows:
        pools[grp].append((sid, ea, name))
    flat = [(sid, ea, name) for sid, ea, name, _, _ in rows]   # score-sorted fallback
    used, xi_ea, slot_to_sid, names = set(), {}, {}, {}

    def take(pool):
        for sid, ea, name in pool:
            if sid not in used:
                used.add(sid)
                return sid, ea, name
        return None

    for slot_no, pc in slots:
        grp = SLOT_GROUP.get(pc)
        if grp == "GK" or grp is None:
            continue
        pick = take(pools[grp]) or take(flat)
        if pick is None:
            continue                            # squad too small (shouldn't happen)
        sid, ea, name = pick
        xi_ea[slot_no], slot_to_sid[slot_no], names[slot_no] = ea, sid, name
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
    """zone_id -> (xt, shot_share). xt = attack-oriented value (B6-C peak ~0.143);
    shot_share = s*g/xt = the fraction of a zone's value that is IMMEDIATE shooting
    (box ~0.75, deep ~0). Conversion (beat-the-keeper) scales only this fraction."""
    out = {}
    for zid, xt, s, g in con.execute(
            "SELECT zone_id, xt, s, g FROM zone_xt").fetchall():
        out[zid] = (xt, (s * g / xt) if xt > 0 else 0.0)
    return out


def load_gk_score(con, nation: str):
    """Top-caps GK shot-stopping = mean(gk_diving, gk_handling, gk_positioning,
    gk_reflexes) from raw EA (GKs have no adjusted attrs). -> (score, name)."""
    r = con.execute(
        "SELECT e.gk_diving, e.gk_handling, e.gk_positioning, e.gk_reflexes, "
        "       s.player_name "
        "FROM wc2026_squad s JOIN ea_fc26_player e ON e.ea_id = s.ea_id "
        "WHERE s.nation_code=? AND s.primary_position_group='GK' "
        "ORDER BY s.caps DESC LIMIT 1", [nation]).fetchone()
    if not r:
        return None, None
    d, h, p, rfx, name = r
    return (d + h + p + rfx) / 4.0, name


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

    # --- steps C + B: value-weight + conversion ---
    # value = entry_share * P(win) * zone_xt * conv_factor
    # conv_factor = (1 - shot_share) + shot_share * conv_rel  (conversion bites only
    # on the shot fraction; conv_rel = 2*BT(finisher, GK), centred 1.0).
    zxt = load_zone_xt(con)
    gk_score, gk_name = load_gk_score(con, "NED")        # ENG attacks NED's keeper
    occ = {z: sum(c["weight"] for c in eng_boards["attack"].get(z, []))
           for z in range(N_BANDS * N_LANES)}
    occ_tot = sum(occ.values()) or 1.0                   # ENG attack budget (~10.0)

    def conv_rel_for(roster):
        # finisher quality = occ-weighted MEAN (beta=0; numbers already counted in
        # P(win)) of finishing+shot_power, +Finishing family boost; vs the GK.
        if not roster or not gk_score:
            return 1.0
        fin = _team_side_score(roster, {"finishing": 0.5, "shot_power": 0.5},
                               ["finishing"], fmult, 0.0)
        return 2.0 * fin / (fin + gk_score) if (fin + gk_score) > 0 else 1.0

    value, index, conv = {}, 0.0, {}
    for z in range(N_BANDS * N_LANES):
        t = threats.get(z)
        if t is None:
            value[z] = None
            continue
        xt_z, shot_share = zxt[z]
        cr = conv_rel_for(build_roster_from_board(con, eng_boards["attack"], z,
                                                  eng_sid, p2f, cache))
        conv[z] = cr
        conv_factor = (1.0 - shot_share) + shot_share * cr
        value[z] = (occ[z] / occ_tot) * t * xt_z * conv_factor
        index += value[z]
    print(f"\n  GK (NED): {gk_name}  shot-stopping={gk_score:.1f}\n")
    _fmt_grid(value, "ENG per-zone VALUE x1000 (entry_share x P(win) x zone_xt x conv):",
              scale=1000.0, dec=3)
    print(f"\n  ENG attacking-value index (sum over zones) = {index:.5f}")
    print("  (per attacking SEQUENCE; pre-VOLUME [step D])")

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
            xt_z, shot_share = zxt[zid]
            cr = conv_rel_for(att)
            cf = (1.0 - shot_share) + shot_share * cr
            print(f"     Socc att={sa:.2f} def={sd:.2f}  P(win)={t:.3f}  |  "
                  f"zone_xt={xt_z:.4f} shot_share={shot_share:.2f} conv_rel={cr:.3f}"
                  f"  ->  VALUE={es * t * xt_z * cf * 1000:.3f} x1000")
    con.close()


def demo_autoxi():
    """Sanity-check the greedy best-XI selection on a few nations."""
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    scores = selection_scores(con)
    for nat in ("ENG", "BRA", "FRA", "ARG", "ESP"):
        _, _, names = autopick_xi(con, nat, "4-3-3", scores)
        gk_score, gk_name = load_gk_score(con, nat)
        xi = ", ".join(names[s] for s in sorted(names))
        gk = f"{gk_name} ({gk_score:.0f})" if gk_name else "none"
        print(f"  {nat} 4-3-3 (+GK {gk}):\n     {xi}")
    con.close()


def _assemble_team(con, nation, cfg, fwd, scores=None, formation="4-3-3"):
    """Auto-pick XI -> assembled phase boards + GK. None if it can't assemble."""
    from src.load.v2_ingest.formation_assembly import assemble, team_boards
    xi_ea, sid, names = autopick_xi(con, nation, formation, scores)
    if not sid:
        return None
    _, slots = assemble(con, formation, nation, cfg, fwd, xi=xi_ea)
    gk_score, _ = load_gk_score(con, nation)
    return {"nation": nation, "sid": sid, "boards": team_boards(slots), "gk": gk_score}


def compute_attack_index(con, att, dfn, zxt, p2f, battle, gate, fmult, beta, cache):
    """A's per-sequence attacking-value index vs B (the demo_real value math,
    factored): sum_z entry_share * P(win) * zone_xt * conv_factor."""
    ab = att["boards"]["attack"]
    occ = {z: sum(c["weight"] for c in ab.get(z, [])) for z in range(N_BANDS * N_LANES)}
    occ_tot = sum(occ.values()) or 1.0
    gk = dfn["gk"]

    def conv_rel(roster):
        if not roster or not gk:
            return 1.0
        fin = _team_side_score(roster, {"finishing": 0.5, "shot_power": 0.5},
                               ["finishing"], fmult, 0.0)
        return 2.0 * fin / (fin + gk) if (fin + gk) > 0 else 1.0

    index = 0.0
    for z in range(N_BANDS * N_LANES):
        att_r = build_roster_from_board(con, ab, z, att["sid"], p2f, cache)
        if not att_r:
            continue
        def_r = build_roster_from_board(con, dfn["boards"]["defence"],
                                        mirror_zone(z), dfn["sid"], p2f, cache)
        key, ctx_name = fold_zone(z)
        threat, *_ = resolve_context(att_r, def_r, battle["zones"][key][ctx_name],
                                     gate, fmult, beta)
        xt_z, shot_share = zxt[z]
        cf = (1.0 - shot_share) + shot_share * conv_rel(att_r)
        index += (occ[z] / occ_tot) * threat * xt_z * cf
    return index


def fit_volume(formation: str = "4-3-3", target: float = 1.178):
    """Round-robin all nations -> attacking-value index distribution -> fit
    VOLUME so mean(team_xG) = target (~1.18 xG/team-match). Reports the spread."""
    import duckdb
    import numpy as np
    from src.load.v2_ingest.formation_assembly import load_config, compute_forwardness
    battle, p2f = load_cfgs()
    gate, fmult = battle["approach_gate"], battle["family_mult"]
    beta = battle.get("aggregation_beta", 1.0)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cfg, fwd, zxt = load_config(), compute_forwardness(con), load_zone_xt(con)
    scores = selection_scores(con)

    nations = [r[0] for r in con.execute(
        "SELECT DISTINCT nation_fifa3 FROM team_playstyle_blended ORDER BY 1").fetchall()]
    cache, teams = {}, {}
    for nat in nations:
        try:
            t = _assemble_team(con, nat, cfg, fwd, scores, formation)
            if t:
                teams[nat] = t
        except SystemExit:
            pass                                  # skip nations we can't assemble
    idx = []
    for a in teams:
        for b in teams:
            if a != b:
                idx.append(compute_attack_index(con, teams[a], teams[b], zxt, p2f,
                                                battle, gate, fmult, beta, cache))
    con.close()
    idx = np.array(idx)
    VOLUME = target / idx.mean()
    xg = idx * VOLUME
    print(f"teams assembled: {len(teams)}/{len(nations)}   matchups: {len(idx)}")
    print(f"index   mean {idx.mean():.5f}  std {idx.std(ddof=1):.5f}")
    print(f"\nVOLUME = {target}/{idx.mean():.5f} = {VOLUME:.1f}\n")
    print(f"team_xG  mean {xg.mean():.3f}  std {xg.std(ddof=1):.3f}  "
          f"(targets: mean 1.18; effective std ~0.45, raw-xG std 0.73)")
    pct = np.percentile(xg, [10, 25, 50, 75, 90])
    print("team_xG  min %.2f | p10 %.2f p25 %.2f p50 %.2f p75 %.2f p90 %.2f | max %.2f"
          % (xg.min(), *pct, xg.max()))


# ----------------------------------------------------------------------------
# (E) Scoreline -- bivariate Poisson (docs/item8_aggregation.md, design E).
# lambda_mean = volume * attack_index; X=Y1+Y3, Y=Y2+Y3, Yi~Pois independent.
# ----------------------------------------------------------------------------
def bivariate_poisson_matrix(l1, l2, l3=0.0, max_goals=10):
    """Joint P(X=x, Y=y) for X=Y1+Y3, Y=Y2+Y3, Yi~Pois(li) independent
    (Karlis-Ntzoufras). l1,l2 are the INDEPENDENT components (= lambda_mean - l3),
    l3 the shared covariance term. l3=0 -> product of two independent Poissons.
    Truncated at max_goals each, renormalised. docs/item8_aggregation.md (E)."""
    import numpy as np
    import math

    def pois(lam):
        k = np.arange(max_goals + 1)
        if lam <= 0:                              # degenerate: all mass at 0
            p = np.zeros(max_goals + 1); p[0] = 1.0; return p
        fact = np.array([math.factorial(int(i)) for i in k], float)
        return np.exp(-lam) * lam ** k / fact

    p1, p2, p3 = pois(l1), pois(l2), pois(l3)
    M = np.zeros((max_goals + 1, max_goals + 1))
    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            M[x, y] = sum(p3[k] * p1[x - k] * p2[y - k]
                          for k in range(min(x, y) + 1))
    return M / M.sum()                            # renormalise the truncated tail


def _matrix_summary(M):
    """W/D/L, expected goals, most-likely scoreline from a scoreline matrix
    (rows = home/X goals, cols = away/Y goals)."""
    import numpy as np
    gx = np.arange(M.shape[0])
    px, py = M.sum(axis=1), M.sum(axis=0)
    x, y = np.unravel_index(np.argmax(M), M.shape)
    return {"p_home": float(np.tril(M, -1).sum()),    # X > Y
            "p_draw": float(np.trace(M)),
            "p_away": float(np.triu(M, 1).sum()),      # Y > X
            "eg_home": float((gx * px).sum()),
            "eg_away": float((gx * py).sum()),
            "ml_score": (int(x), int(y)), "ml_p": float(M[x, y])}


def _scoreline_setup(formation):
    """Shared load: configs + read-only DB handle + derived inputs. Returns
    (con, packed) where packed bundles everything compute_attack_index needs."""
    import duckdb
    from src.load.v2_ingest.formation_assembly import load_config, compute_forwardness
    battle, p2f = load_cfgs()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    packed = dict(battle=battle, p2f=p2f, gate=battle["approach_gate"],
                  fmult=battle["family_mult"], beta=battle.get("aggregation_beta", 1.0),
                  volume=battle.get("volume", 199.4), cfg=load_config(),
                  fwd=compute_forwardness(con), zxt=load_zone_xt(con),
                  scores=selection_scores(con), cache={})
    return con, packed


def _lambda_pair(con, ta, tb, P):
    """Both lambda-means for the matchup A vs B (volume * attack index each way)."""
    ia = compute_attack_index(con, ta, tb, P["zxt"], P["p2f"], P["battle"],
                              P["gate"], P["fmult"], P["beta"], P["cache"])
    ib = compute_attack_index(con, tb, ta, P["zxt"], P["p2f"], P["battle"],
                              P["gate"], P["fmult"], P["beta"], P["cache"])
    return P["volume"] * ia, P["volume"] * ib


def demo_scoreline(nation_a="ESP", nation_b="ENG", formation="4-3-3", l3=0.0):
    """Assemble both XIs -> lambda-means -> bivariate-Poisson scoreline matrix.
    Face-validity probe for step E."""
    con, P = _scoreline_setup(formation)
    try:
        ta = _assemble_team(con, nation_a, P["cfg"], P["fwd"], P["scores"], formation)
        tb = _assemble_team(con, nation_b, P["cfg"], P["fwd"], P["scores"], formation)
    except SystemExit as e:
        con.close(); sys.exit(str(e))
    if not ta or not tb:
        con.close(); sys.exit(f"could not assemble {nation_a if not ta else nation_b}")
    lam_a, lam_b = _lambda_pair(con, ta, tb, P)
    con.close()
    l1, l2 = max(lam_a - l3, 0.0), max(lam_b - l3, 0.0)
    M = bivariate_poisson_matrix(l1, l2, l3)
    s = _matrix_summary(M)
    print(f"\n{nation_a} vs {nation_b}  (formation {formation}, lambda3={l3})")
    print(f"lambda-mean:  {nation_a} {lam_a:.3f}   {nation_b} {lam_b:.3f}")
    print(f"P(win) {nation_a} {s['p_home']*100:.1f}% | draw {s['p_draw']*100:.1f}% | "
          f"{nation_b} {s['p_away']*100:.1f}%")
    print(f"most-likely {s['ml_score'][0]}-{s['ml_score'][1]} (p={s['ml_p']*100:.1f}%)  "
          f"E[goals] {s['eg_home']:.2f}-{s['eg_away']:.2f}")
    print(f"\nscoreline %  (rows={nation_a} goals, cols={nation_b} goals), 0..5:")
    print("      " + "".join(f"{c:>7}" for c in range(6)))
    for x in range(6):
        print(f"  {x}: " + "".join(f"{M[x, y]*100:7.1f}" for y in range(6)))


def validate_scoreline(formation="4-3-3", l3=0.0):
    """Round-robin all assemblable nations -> aggregate team-match goal pmf +
    mean draw rate vs the empirical S37 acceptance test."""
    import numpy as np
    con, P = _scoreline_setup(formation)
    nations = [r[0] for r in con.execute(
        "SELECT DISTINCT nation_fifa3 FROM team_playstyle_blended ORDER BY 1").fetchall()]
    teams = {}
    for nat in nations:
        try:
            t = _assemble_team(con, nat, P["cfg"], P["fwd"], P["scores"], formation)
            if t:
                teams[nat] = t
        except SystemExit:
            pass
    max_goals, goals, draws, n = 10, np.zeros(11), [], 0
    for a in teams:
        for b in teams:
            if a == b:
                continue
            lam_a, lam_b = _lambda_pair(con, teams[a], teams[b], P)
            l1, l2 = max(lam_a - l3, 0.0), max(lam_b - l3, 0.0)
            M = bivariate_poisson_matrix(l1, l2, l3, max_goals)
            goals += M.sum(axis=1)                # team A's marginal goal pmf
            draws.append(np.trace(M))
            n += 1
    con.close()
    goals /= n
    k = np.arange(max_goals + 1)
    mean = (k * goals).sum()
    var = ((k - mean) ** 2 * goals).sum()
    emp = np.array([134, 138, 81, 30, 9, 6], float); emp /= emp.sum()
    print(f"teams {len(teams)}/{len(nations)}   matchups {n}   lambda3={l3}")
    print(f"team-match goals: mean {mean:.3f}  var {var:.3f}  var/mean {var/mean:.3f}"
          f"   (empirical 1.18; predicted ~1.29 at full 0.588 spread)")
    print(f"mean draw rate {np.mean(draws)*100:.1f}%   (empirical intl ~25-28%)")
    print("\ngoals    model   empirical")
    for g in range(6):
        m = goals[g] if g < 5 else goals[5:].sum()
        lbl = f"{g}+" if g == 5 else f"{g} "
        print(f"  {lbl}    {m*100:5.1f}%   {emp[g]*100:5.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthetic numbers test")
    ap.add_argument("--fold-table", action="store_true", help="print 30->9 fold")
    ap.add_argument("--demo-real", action="store_true", help="ENG vs NED real sweep")
    ap.add_argument("--autoxi", action="store_true", help="validate greedy best-XI")
    ap.add_argument("--fit-volume", action="store_true", help="round-robin VOLUME fit")
    ap.add_argument("--scoreline", nargs=2, metavar=("A", "B"),
                    help="demo bivariate-Poisson scoreline, FIFA3 A vs B")
    ap.add_argument("--validate-scoreline", action="store_true",
                    help="round-robin goals-dist + draw-rate vs empirical")
    ap.add_argument("--l3", type=float, default=0.0,
                    help="bivariate-Poisson covariance term (default 0)")
    a = ap.parse_args()
    if a.demo:
        demo()
    elif a.fold_table:
        fold_table()
    elif a.demo_real:
        demo_real()
    elif a.autoxi:
        demo_autoxi()
    elif a.fit_volume:
        fit_volume()
    elif a.scoreline:
        demo_scoreline(a.scoreline[0], a.scoreline[1], l3=a.l3)
    elif a.validate_scoreline:
        validate_scoreline(l3=a.l3)
    else:
        print("try: --fold-table | --demo | --demo-real | --autoxi | --fit-volume "
              "| --scoreline A B | --validate-scoreline")


if __name__ == "__main__":
    main()
