"""
_probe_coverage_audit.py — S27 probe (deletable). Per-player + per-nation
data-source coverage across the FOUR sources the model can draw on:
  EA prior · top-5 domestic (Understat, xG) · European cups (FBref UCL/UEL/UECL)
  · international tournaments (StatsBomb).

Name-based where the resolver ids don't bridge: our_player_id reaches the FBref
cups but NOT Understat (disjoint id spaces — the cross-source identity gap), so
top-5 + intl presence is detected by hardened name (+nation for intl), while
EA (ea_id) and cups (our_player_id) reuse the resolver-confirmed links.

Read-only. Measures, decides nothing.

    uv run python src/load/v2_ingest/_probe_coverage_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

DB = "data/processed/worldcup.duckdb"
NATION = Path("data/config/nation_codes.json")
SB_ALIASES = {
    "Korea Republic": "KOR", "Republic of Korea": "KOR", "South Korea": "KOR",
    "IR Iran": "IRN", "Côte d'Ivoire": "CIV", "Cote d'Ivoire": "CIV",
    "Democratic Republic of Congo": "COD", "Congo DR": "COD",
    "Cabo Verde": "CPV", "Cape Verde Islands": "CPV",
    "Czechia": "CZE", "Türkiye": "TUR", "Turkiye": "TUR", "USA": "USA",
}


def hard(s):
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def main() -> int:
    nm = json.loads(NATION.read_text(encoding="utf-8"))
    nm.pop("_comment", None)
    team2code = {**nm, **SB_ALIASES}

    con = duckdb.connect(DB, read_only=True)
    squad = con.sql(
        "SELECT squad_row_id, name_norm, nation_code, position_class, ea_id, "
        "our_player_id FROM wc2026_squad").df()

    # top-5 (Understat): aggregate by hardened name (no nation on Understat)
    t5 = con.sql(
        "SELECT lower(strip_accents(pl.player_name)) AS nn, "
        "count(*) AS m, sum(p.minutes) AS mins, sum(p.xg) AS xg "
        "FROM player_match_stats p JOIN players pl ON p.player_id = pl.player_id "
        "GROUP BY 1").df()
    t5["h"] = t5["nn"].map(hard)
    t5g = t5.groupby("h").agg(m=("m", "sum"), mins=("mins", "sum")).to_dict("index")

    # cups (FBref): by resolver-confirmed our_player_id
    cup = con.sql(
        "SELECT player_id, count(*) AS m, sum(minutes) AS mins "
        "FROM player_match_fbref GROUP BY 1").df()
    cupd = cup.set_index("player_id")[["m", "mins"]].to_dict("index")

    # intl (StatsBomb): by hardened name + nation (team -> code)
    sb = con.sql(
        "SELECT lower(strip_accents(player)) AS nn, team, "
        "count(DISTINCT match_id) AS m "
        "FROM statsbomb_event WHERE player_id IS NOT NULL GROUP BY 1,2").df()
    sb["code"] = sb["team"].map(team2code)
    sb["h"] = sb["nn"].map(hard)
    sbg: dict = {}
    for r in sb.dropna(subset=["code"]).itertuples():
        sbg[(r.h, r.code)] = sbg.get((r.h, r.code), 0) + int(r.m)
    con.close()

    rows = []
    for r in squad.itertuples():
        h = hard(r.name_norm)
        opid = int(r.our_player_id) if pd.notna(r.our_player_id) else None
        cup_rec = cupd.get(opid) if opid is not None else None
        t5_rec = t5g.get(h)
        ea = bool(pd.notna(r.ea_id))
        top5 = t5_rec is not None
        cups = cup_rec is not None
        intl = (h, r.nation_code) in sbg
        emp = top5 or cups or intl
        rows.append({
            "nat": r.nation_code, "pos": r.position_class,
            "ea": ea, "top5": top5, "cups": cups,
            "intl": intl, "emp": emp, "anysrc": ea or emp, "dark": not (ea or emp),
            # build-up involvement = Understat xGChain/xGBuildup (top5);
            # defensive actions = tackles/interceptions/duels (cups OR intl)
            "buildup": top5, "def_action": cups or intl,
            "t5_mins": float((t5_rec or {}).get("mins") or 0),
            "cup_mins": float((cup_rec or {}).get("mins") or 0),
            "nsrc": int(ea) + int(top5) + int(cups) + int(intl),
        })
    d = pd.DataFrame(rows)
    n = len(d)

    print(f"squad players: {n}")
    print("\nper-source coverage (of squad):")
    for c in ["ea", "top5", "cups", "intl", "emp", "anysrc", "dark"]:
        print(f"  {c:8}: {int(d[c].sum())}  ({100*d[c].mean():.1f}%)")
    print("\nsources-per-player (0-4 of EA/top5/cups/intl):")
    print(d["nsrc"].value_counts().sort_index().to_string())

    g = d.groupby("nat").agg(
        squad=("nat", "size"), ea=("ea", "sum"), top5=("top5", "sum"),
        cups=("cups", "sum"), intl=("intl", "sum"),
        anysrc=("anysrc", "sum"), dark=("dark", "sum")).reset_index()
    g["cov%"] = (100 * g["anysrc"] / g["squad"]).round(0).astype(int)
    g = g.sort_values(["dark", "nat"], ascending=[False, True])
    print(f"\nPER-NATION coverage ({len(g)} nations, sorted by dark desc):")
    print(g.to_string(index=False))

    # --- defensive-action / build-up coverage, by position ---
    d["att_only"] = d["top5"] & ~d["def_action"]   # build-up but no def actions
    print("\n=== DEFENSIVE-ACTION coverage (tackles/int/duels via cups|intl) ===")
    print(f"  squad with ANY defensive-action source : {int(d['def_action'].sum())} "
          f"({100*d['def_action'].mean():.1f}%)")
    print(f"  squad with build-up only (top5, no def): {int(d['att_only'].sum())}")
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    p = d.groupby("pos").agg(
        squad=("pos", "size"), buildup=("buildup", "sum"),
        cups=("cups", "sum"), intl=("intl", "sum"),
        def_action=("def_action", "sum"), any_emp=("emp", "sum"),
        dark=("dark", "sum")).reset_index()
    p["def%"] = (100 * p["def_action"] / p["squad"]).round(0).astype(int)
    p = p.sort_values("pos", key=lambda s: s.map(order))
    print("\nby position_class (buildup=Understat xGChain/Buildup; "
          "def_action=cups|intl):")
    print(p.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
