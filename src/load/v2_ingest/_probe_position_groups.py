"""
_probe_position_groups.py — S27 probe (deletable). Validate _position_groups
maps: assign each squad player a PRIMARY coarse group = the group holding the
most of their minutes across all 3 sources (name-based, since ids don't bridge),
Wikipedia position_class as fallback for the dark. Read-only.

    uv run python src/load/v2_ingest/_probe_position_groups.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

import _position_groups as pg

DB = "data/processed/worldcup.duckdb"
NATION = Path("data/config/nation_codes.json")
SB_ALIASES = {"Korea Republic": "KOR", "Republic of Korea": "KOR",
              "South Korea": "KOR", "IR Iran": "IRN", "Côte d'Ivoire": "CIV",
              "Cote d'Ivoire": "CIV", "Democratic Republic of Congo": "COD",
              "Congo DR": "COD", "Cabo Verde": "CPV", "Cape Verde Islands": "CPV",
              "Czechia": "CZE", "Türkiye": "TUR", "Turkiye": "TUR", "USA": "USA"}
WIKI = {"GK": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}


def hard(s):
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def add(d, grp, mins):
    if grp:
        d[grp] = d.get(grp, 0) + (mins or 0)


def main() -> int:
    nm = json.loads(NATION.read_text(encoding="utf-8")); nm.pop("_comment", None)
    t2c = {**nm, **SB_ALIASES}
    con = duckdb.connect(DB, read_only=True)

    squad = con.sql("SELECT squad_row_id, name_norm, nation_code, position_class, "
                    "our_player_id FROM wc2026_squad").df()

    # FBref minutes per (player_id, effective_position)
    fb = con.sql("SELECT player_id, effective_position p, sum(minutes) m "
                 "FROM player_match_fbref GROUP BY 1,2").df()
    fb_by_pid: dict = {}
    for r in fb.itertuples():
        add(fb_by_pid.setdefault(r.player_id, {}), pg.coarse("fbref", r.p), r.m)

    # Understat minutes per (hardnorm name, effective_position)
    us = con.sql("SELECT lower(strip_accents(pl.player_name)) nn, "
                 "p.effective_position p, sum(p.minutes) m "
                 "FROM player_match_stats p JOIN players pl ON p.player_id=pl.player_id "
                 "GROUP BY 1,2").df()
    us_by_name: dict = {}
    for r in us.itertuples():
        add(us_by_name.setdefault(hard(r.nn), {}), pg.coarse("understat", r.p), r.m)

    # StatsBomb: modal event position per player_id + total derived minutes
    sbpos = con.sql("SELECT player_id, position, count(*) c FROM statsbomb_event "
                    "WHERE position IS NOT NULL GROUP BY 1,2").df()
    modal = sbpos.sort_values("c").groupby("player_id")["position"].last().to_dict()
    sbmin = con.sql("SELECT player_id, lower(strip_accents(player)) nn, team, "
                    "sum(minutes) m FROM statsbomb_player_match GROUP BY 1,2,3").df()
    sb_by_name: dict = {}
    for r in sbmin.itertuples():
        code = t2c.get(r.team)
        grp = pg.coarse("statsbomb", modal.get(r.player_id))
        if code:
            add(sb_by_name.setdefault((hard(r.nn), code), {}), grp, r.m)
    con.close()

    rows = []
    for r in squad.itertuples():
        h = hard(r.name_norm)
        mins: dict = {}
        opid = int(r.our_player_id) if pd.notna(r.our_player_id) else None
        for src in (fb_by_pid.get(opid, {}), us_by_name.get(h, {}),
                    sb_by_name.get((h, r.nation_code), {})):
            for g, m in src.items():
                mins[g] = mins.get(g, 0) + m
        if mins:
            primary = max(mins, key=mins.get)
            method = "empirical"
        else:
            primary = WIKI.get(r.position_class)
            method = "wiki-fallback"
        rows.append({"sqid": r.squad_row_id, "name": r.name_norm,
                     "nat": r.nation_code, "wiki": r.position_class,
                     "primary": primary, "method": method,
                     "moved": primary != WIKI.get(r.position_class)})
    d = pd.DataFrame(rows)

    print("primary-group distribution:")
    print(d["primary"].value_counts(dropna=False).to_string())
    print("\nassignment method:", d["method"].value_counts().to_dict())
    print("\nreclassified vs Wikipedia (empirical only):",
          int((d["moved"] & (d["method"] == "empirical")).sum()))
    mv = d[d["moved"] & (d["method"] == "empirical")]
    print("  movement (wiki -> primary):")
    print(mv.groupby(["wiki", "primary"]).size().sort_values(ascending=False).to_string())

    print("\nspot checks:")
    for who in ["mohamed salah", "trent", "rodri", "virgil", "haaland",
                "kevin de bruyne", "joshua kimmich"]:
        hit = d[d["name"].str.contains(who, na=False)]
        for r in hit.head(2).itertuples():
            print(f"  {r.name:24} [{r.nat}] wiki={r.wiki} -> {r.primary} ({r.method})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
