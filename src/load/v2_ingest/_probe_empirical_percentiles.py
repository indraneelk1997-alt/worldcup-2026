"""
_probe_empirical_percentiles.py — S27 probe (deletable). Empirical per-90
percentiles for squad players in 3 dimensions mirroring the EA buckets.

Attack     = (goals + xa) /90                       [Understat; FBref g+a fallback]
              = (xg+xa) goal-threat + (goals-xg) finishing bonus  (maintainer S27)
Possession = (key_passes + xg_buildup + xg_chain) /90  [Understat]
Defense    = blend of:
   * padj ball-winning = (tackles_won+interceptions)/90 x (50 / opp_possession%)
     (possession-adjusted so dominant-team CBs aren't punished for low volume)
   * shot-suppression  = minutes-weighted (opp SoT faced + goals conceded) per
     match, inverted (fewer = better) — solidity the action-counts miss.
   Defense = 0.6*padj_pct + 0.4*suppression_pct   (within position group)
Percentiles WITHIN primary_position_group. Club data only (v1). Read-only.

    uv run python src/load/v2_ingest/_probe_empirical_percentiles.py
"""
from __future__ import annotations

import re
import sys

import duckdb
import numpy as np
import pandas as pd

DB = "data/processed/worldcup.duckdb"
MIN_MINS = 270
PADJ_W, SUPP_W = 0.6, 0.4


def hard(s):
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def main() -> int:
    pd.set_option("display.width", 220)
    con = duckdb.connect(DB, read_only=True)
    sq = con.sql("SELECT name_norm, nation_code nat, primary_position_group grp, "
                 "our_player_id FROM wc2026_squad").df()

    # Understat: attack + possession inputs, by hardened name
    us = con.sql("SELECT lower(strip_accents(pl.player_name)) nn, sum(p.minutes) mins, "
                 "sum(p.goals) g, sum(p.xa) xa, sum(p.key_passes) kp, "
                 "sum(p.xg_buildup) xgb, sum(p.xg_chain) xgc, sum(p.assists) a "
                 "FROM player_match_stats p JOIN players pl ON p.player_id=pl.player_id "
                 "GROUP BY 1").df()
    us["h"] = us["nn"].map(hard)
    us = us.groupby("h")[["mins", "g", "xa", "kp", "xgb", "xgc", "a"]].sum()

    # FBref attack fallback (goals+assists)
    fba = con.sql("SELECT player_id, sum(minutes) mins, sum(goals) g, sum(assists) a "
                  "FROM player_match_fbref GROUP BY 1").df().set_index("player_id")

    # FBref defense v2 — per player-match with opponent context
    dfm = con.sql("""
        WITH team_shots AS (
          SELECT game_id, team, sum(shots_on_target) sot FROM player_match_fbref GROUP BY 1,2
        )
        SELECT p.player_id, p.minutes,
               (p.tackles_won + p.interceptions) AS actions,
               (100 - t.possession) AS opp_poss,
               t.opponent_goals AS opp_goals,
               COALESCE(ts.sot, 0) AS opp_sot
        FROM player_match_fbref p
        JOIN team_match_fbref t ON p.game_id=t.game_id AND p.team=t.team
        LEFT JOIN team_shots ts ON ts.game_id=p.game_id AND ts.team=t.opponent
    """).df()
    con.close()

    print("possession sanity:", dfm["opp_poss"].notna().sum(), "of", len(dfm),
          "player-matches have possession; avg opp_poss",
          round(dfm["opp_poss"].mean(), 1))

    # aggregate defense per player_id
    g = dfm.groupby("player_id")
    dW = g.apply(lambda x: pd.Series({
        "mins": x["minutes"].sum(),
        "actions": x["actions"].sum(),
        "avg_opp_poss": np.average(x["opp_poss"], weights=x["minutes"]),
        "supp": np.average(x["opp_sot"] + x["opp_goals"], weights=x["minutes"]),
    }))
    dW["padj"] = (dW["actions"] / dW["mins"] * 90) * (50.0 / dW["avg_opp_poss"])

    rows = []
    for r in sq.itertuples():
        h = hard(r.name_norm)
        opid = int(r.our_player_id) if pd.notna(r.our_player_id) else None
        u = us.loc[h] if h in us.index else None
        f = fba.loc[opid] if (opid is not None and opid in fba.index) else None
        d = dW.loc[opid] if (opid is not None and opid in dW.index) else None
        um = float(u["mins"]) if u is not None else 0.0

        att = ((u["g"] + u["xa"]) / um * 90) if um >= MIN_MINS else (
            ((f["g"] + f["a"]) / f["mins"] * 90) if (f is not None and f["mins"] >= MIN_MINS) else np.nan)
        pos = ((u["kp"] + u["xgb"] + u["xgc"]) / um * 90) if um >= MIN_MINS else np.nan
        rows.append({"name": r.name_norm, "nat": r.nat, "grp": r.grp,
                     "mins": max(um, float(d["mins"]) if d is not None else 0.0),
                     "Attack": att, "Possession": pos,
                     "padj": float(d["padj"]) if (d is not None and d["mins"] >= MIN_MINS) else np.nan,
                     "supp": float(d["supp"]) if (d is not None and d["mins"] >= MIN_MINS) else np.nan})
    d = pd.DataFrame(rows)

    d["Attack_pct"] = d.groupby("grp")["Attack"].rank(pct=True) * 100
    d["Possession_pct"] = d.groupby("grp")["Possession"].rank(pct=True) * 100
    d["padj_pct"] = d.groupby("grp")["padj"].rank(pct=True) * 100
    d["supp_pct"] = d.groupby("grp")["supp"].rank(pct=True, ascending=False) * 100  # fewer=better
    d["Defense"] = PADJ_W * d["padj_pct"] + SUPP_W * d["supp_pct"]

    print("coverage:", {k: int(d[k].notna().sum()) for k in ["Attack", "Possession", "Defense"]})

    def table(dim, grp, extra=()):
        sub = d[(d["grp"] == grp) & d[dim].notna()].copy()
        cols = ["name", "nat", "mins", *extra, dim, f"{dim}_pct"] if f"{dim}_pct" in d else \
               ["name", "nat", "mins", "padj", "supp", "Defense"]
        fmt = {c: "{:.2f}".format for c in [dim, "padj", "supp"] if c in cols}
        fmt.update({"mins": "{:.0f}".format})
        if f"{dim}_pct" in d: fmt[f"{dim}_pct"] = "{:.0f}".format
        if "Defense" in cols: fmt["Defense"] = "{:.0f}".format
        print(f"\n=== {dim} — TOP 10 among {grp} (n={len(sub)}) ===")
        print(sub.sort_values(dim, ascending=False).head(10).to_string(index=False, columns=cols, formatters=fmt))
        print(f"--- {dim} — BOTTOM 10 among {grp} ---")
        print(sub.sort_values(dim).head(10).to_string(index=False, columns=cols, formatters=fmt))

    table("Attack", "FWD")
    table("Possession", "MID")
    table("Defense", "DEF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
