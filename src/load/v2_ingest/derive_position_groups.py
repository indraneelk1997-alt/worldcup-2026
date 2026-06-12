"""
S27 — assign each WC2026 squad player a PRIMARY position group {GK,DEF,MID,FWD}
and persist the per-source appearance profile.

Primary = the coarse group holding the most MINUTES across all 3 sources
(name-based, since ids don't bridge), via _position_groups maps. GK GUARD:
GK is set by the squad (Wikipedia) — an outfielder is never reassigned to GK
and a squad GK stays GK regardless of empirical (handles name-collisions /
emergency-keeper cameos). Dark players (no empirical) → Wikipedia fallback.

Persists:
  * wc2026_squad.primary_position_group  (new col; app-enforced)
  * squad_position_profile  (squad_row_id, source, position_group, matches,
    minutes) — kept for the percentile/averaging step. DERIVED → --apply rebuilds.
    NOTE: the profile keeps ALL appearances incl. stray GK cameos (transparency);
    only the PRIMARY assignment applies the guard.

Default DRY-RUN; --apply writes.

    uv run python src/load/v2_ingest/derive_position_groups.py            # dry-run
    uv run python src/load/v2_ingest/derive_position_groups.py --apply    # write
"""
from __future__ import annotations

import argparse
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


def hard(s):
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def acc(d, grp, matches, minutes):
    if grp:
        e = d.setdefault(grp, [0, 0])
        e[0] += int(matches or 0); e[1] += int(minutes or 0)


def column_exists(con, table, col) -> bool:
    return con.execute("SELECT 1 FROM information_schema.columns WHERE "
                       "table_name=? AND column_name=?", [table, col]).fetchone() is not None


def build(con):
    nm = json.loads(NATION.read_text(encoding="utf-8")); nm.pop("_comment", None)
    t2c = {**nm, **SB_ALIASES}

    squad = con.sql("SELECT squad_row_id, name_norm, nation_code, position_class, "
                    "our_player_id FROM wc2026_squad").df()

    fb = con.sql("SELECT player_id, effective_position p, count(*) c, sum(minutes) m "
                 "FROM player_match_fbref GROUP BY 1,2").df()
    fb_by_pid: dict = {}
    for r in fb.itertuples():
        acc(fb_by_pid.setdefault(r.player_id, {}), pg.coarse("fbref", r.p), r.c, r.m)

    us = con.sql("SELECT lower(strip_accents(pl.player_name)) nn, "
                 "p.effective_position p, count(*) c, sum(p.minutes) m "
                 "FROM player_match_stats p JOIN players pl ON p.player_id=pl.player_id "
                 "GROUP BY 1,2").df()
    us_by_name: dict = {}
    for r in us.itertuples():
        acc(us_by_name.setdefault(hard(r.nn), {}), pg.coarse("understat", r.p), r.c, r.m)

    sbpos = con.sql("SELECT player_id, position, count(*) c FROM statsbomb_event "
                    "WHERE position IS NOT NULL GROUP BY 1,2").df()
    modal = sbpos.sort_values("c").groupby("player_id")["position"].last().to_dict()
    sbm = con.sql("SELECT player_id, lower(strip_accents(player)) nn, team, "
                  "count(*) c, sum(minutes) m FROM statsbomb_player_match "
                  "GROUP BY 1,2,3").df()
    sb_by_name: dict = {}
    for r in sbm.itertuples():
        code = t2c.get(r.team)
        if code:
            acc(sb_by_name.setdefault((hard(r.nn), code), {}),
                pg.coarse("statsbomb", modal.get(r.player_id)), r.c, r.m)

    prof_rows, prim_rows = [], []
    for r in squad.itertuples():
        h = hard(r.name_norm)
        opid = int(r.our_player_id) if pd.notna(r.our_player_id) else None
        per_src = {"fbref": fb_by_pid.get(opid, {}), "understat": us_by_name.get(h, {}),
                   "statsbomb": sb_by_name.get((h, r.nation_code), {})}
        total: dict = {}
        for src, gd in per_src.items():
            for g, (mt, mn) in gd.items():
                prof_rows.append({"squad_row_id": r.squad_row_id, "source": src,
                                  "position_group": g, "matches": mt, "minutes": mn})
                e = total.setdefault(g, [0, 0]); e[0] += mt; e[1] += mn

        if r.position_class == "GK":                      # GK guard: squad wins
            primary, method = "GK", "wiki-gk"
        else:
            cand = {g: v for g, v in total.items() if g != "GK"}   # outfield never GK
            if cand:
                primary = max(cand, key=lambda g: cand[g][1])
                method = "empirical"
            else:
                primary = r.position_class
                method = "wiki-fallback"
        prim_rows.append({"squad_row_id": r.squad_row_id, "name": r.name_norm,
                          "nat": r.nation_code, "wiki": r.position_class,
                          "primary": primary, "method": method})
    return pd.DataFrame(prof_rows), pd.DataFrame(prim_rows)


def main(apply: bool) -> int:
    con = duckdb.connect(DB, read_only=not apply)
    prof, prim = build(con)

    print("=" * 60)
    print(f"  Position groups — {'APPLY' if apply else 'DRY-RUN'}")
    print("=" * 60)
    print("primary-group distribution:")
    print(prim["primary"].value_counts(dropna=False).to_string())
    print("\nmethod:", prim["method"].value_counts().to_dict())
    moved = prim[(prim["primary"] != prim["wiki"]) & (prim["method"] == "empirical")]
    print(f"\nreclassified vs Wikipedia: {len(moved)}")
    print(moved.groupby(["wiki", "primary"]).size().sort_values(ascending=False).to_string())
    print("  (MID->GK should now be 0 — GK guard)")
    print("\nspot checks:")
    for who in ["mohamed salah", "kevin de bruyne", "joshua kimmich",
                "virgil van dijk", "erling haaland"]:
        for r in prim[prim["name"].str.contains(who, na=False)].head(1).itertuples():
            print(f"  {r.name:22} wiki={r.wiki} -> {r.primary}")
    print(f"\nprofile rows: {len(prof)} (squad x source x group)")

    if apply:
        if not column_exists(con, "wc2026_squad", "primary_position_group"):
            con.execute("ALTER TABLE wc2026_squad ADD COLUMN primary_position_group VARCHAR")
        con.register("prim", prim[["squad_row_id", "primary"]])
        con.execute("UPDATE wc2026_squad t SET primary_position_group=p.primary "
                    "FROM prim p WHERE t.squad_row_id=p.squad_row_id")
        con.register("prof", prof)
        con.execute("CREATE OR REPLACE TABLE squad_position_profile AS SELECT * FROM prof")
        con.unregister("prim"); con.unregister("prof")
        print("\nAPPLIED — wc2026_squad.primary_position_group + squad_position_profile.")
    else:
        print("\nDRY-RUN — no writes.")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    args = ap.parse_args()
    sys.exit(main(apply=args.apply))
