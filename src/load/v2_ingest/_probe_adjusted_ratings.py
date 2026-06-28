"""
_probe_adjusted_ratings.py — S27 (deletable). THE adjusted ratings: blend the
EA role rating (prior) toward empirical performance, per dimension.

Per dimension d in {Attack, Possession, Defense}, all as percentiles within
primary_position_group:
    adjusted_pct = (1 - lambda_d)*EA_role_pct + lambda_d*empirical_pct
    lambda_d = min(minutes_d / 900, 1) * CAP_d        # CAP = per-dim confidence
    CAP (LOCKED S28, see docs/blend_redesign.md): Attack 0.60 / Possession 0.50 /
         Defense 0.25. The ordering encodes data reliability (Understat xG best ->
         most empirical weight; cups counting-stat proxy worst -> least). Symmetric
         blend; the low CAP already bounds the max swing to CAP*100, so no
         asymmetry/clamp needed. Override per-run via CAP_ATT/CAP_POSS/CAP_DEF env.

Empirical (club, v1):
  Attack     = (goals + xa)/90                         [Understat ONLY now]
  Possession = (key_passes + xg_buildup + xg_chain)/90 [Understat]
  Defense    = 0.6*padj_pct + 0.4*suppression_pct      [FBref cups, v2]
EA role rating from _ea_attribute_buckets. Read-only.

    uv run python src/load/v2_ingest/_probe_adjusted_ratings.py
"""
from __future__ import annotations

import os
import re
import sys

import duckdb
import numpy as np
import pandas as pd

import _ea_attribute_buckets as eab

DB = "data/processed/worldcup.duckdb"
MIN_MINS, SAT = 270, 900
CAP = {
    "Attack": float(os.environ.get("CAP_ATT", 0.60)),
    "Possession": float(os.environ.get("CAP_POSS", 0.50)),
    "Defense": float(os.environ.get("CAP_DEF", 0.25)),
}
PADJ_W, SUPP_W = 0.6, 0.4
DIMS = ["Attack", "Possession", "Defense"]

# Option A (S28, docs/blend_redesign.md): only blend dimensions where the position
# group makes the empirical signal meaningful; off-role dims stay at the pure EA
# prior (lam forced to 0). DEF attacking = goals+xa set-piece noise; FWD defending
# = cups-tackle noise. MID (pivots/box-to-box, NOT CAMs/wingers) keeps all three.
RELEVANT = {
    "DEF": {"Possession", "Defense"},
    "MID": {"Attack", "Possession", "Defense"},
    "FWD": {"Attack", "Possession"},
}


def hard(s):
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def build(con):
    """Construct the per-player blended-ratings dataframe (read-only). Returns df
    with ea_<dim>/ea_<dim>_pct/adj_<dim>/lam_<dim> etc. Caller owns the connection
    (so other probes can reuse this without re-deriving the empirical pipeline)."""
    sq = con.sql("SELECT squad_row_id, name_norm, nation_code nat, primary_position_group grp, "
                 "ea_id, our_player_id, understat_player_id FROM wc2026_squad").df()

    ea = eab.add_ratings(con.sql(
        f"SELECT {', '.join(['ea_id'] + eab.ALL_ATTRS)} FROM ea_fc26_player").df())
    ea = ea[["ea_id"] + DIMS].rename(columns={d: f"ea_{d}" for d in DIMS})
    sq = sq.merge(ea, on="ea_id", how="left")

    # Understat aggregated BY player_id, looked up via wc2026_squad.understat_player_id
    # (resolve_understat_links.py). Replaces the old hardened-NAME match, which
    # dropped variant-name players (Mbappé->"Mbappe-Lottin") and summed distinct
    # same-name players (the two Vitinhas). S45 / docs/understat_relink.md.
    us = con.sql("SELECT p.player_id, sum(p.minutes) mins, sum(p.goals) g, "
                 "sum(p.xa) xa, sum(p.key_passes) kp, sum(p.xg_buildup) xgb, "
                 "sum(p.xg_chain) xgc FROM player_match_stats p "
                 "GROUP BY 1").df().set_index("player_id")

    dfm = con.sql("""
        WITH team_shots AS (
          SELECT game_id, team, sum(shots_on_target) sot FROM player_match_fbref GROUP BY 1,2)
        SELECT p.player_id, p.minutes, (p.tackles_won+p.interceptions) actions,
               (100-t.possession) opp_poss, t.opponent_goals opp_goals,
               COALESCE(ts.sot,0) opp_sot
        FROM player_match_fbref p
        JOIN team_match_fbref t ON p.game_id=t.game_id AND p.team=t.team
        LEFT JOIN team_shots ts ON ts.game_id=p.game_id AND ts.team=t.opponent
    """).df()

    dW = dfm.groupby("player_id").apply(lambda x: pd.Series({
        "mins": x["minutes"].sum(),
        "padj": (x["actions"].sum() / x["minutes"].sum() * 90)
                * (50.0 / np.average(x["opp_poss"], weights=x["minutes"])),
        "supp": np.average(x["opp_sot"] + x["opp_goals"], weights=x["minutes"]),
    }))

    rows = []
    for r in sq.itertuples():
        opid = int(r.our_player_id) if pd.notna(r.our_player_id) else None
        upid = int(r.understat_player_id) if pd.notna(r.understat_player_id) else None
        u = us.loc[upid] if (upid is not None and upid in us.index) else None
        d = dW.loc[opid] if (opid is not None and opid in dW.index) else None
        um = float(u["mins"]) if u is not None else 0.0
        dm = float(d["mins"]) if d is not None else 0.0
        rows.append({
            "squad_row_id": r.squad_row_id, "ea_id": r.ea_id,
            "name": r.name_norm, "nat": r.nat, "grp": r.grp,
            "ea_Attack": r.ea_Attack, "ea_Possession": r.ea_Possession, "ea_Defense": r.ea_Defense,
            "Attack": ((u["g"] + u["xa"]) / um * 90) if um >= MIN_MINS else np.nan,
            "Possession": ((u["kp"] + u["xgb"] + u["xgc"]) / um * 90) if um >= MIN_MINS else np.nan,
            "padj": float(d["padj"]) if dm >= MIN_MINS else np.nan,
            "supp": float(d["supp"]) if dm >= MIN_MINS else np.nan,
            "att_min": um, "def_min": dm,
        })
    df = pd.DataFrame(rows)
    df = df[df["grp"] != "GK"].reset_index(drop=True)   # GKs = separate track, excluded here

    # empirical percentiles within group
    for d in ["Attack", "Possession"]:
        df[f"emp_{d}_pct"] = df.groupby("grp")[d].rank(pct=True) * 100
    df["padj_pct"] = df.groupby("grp")["padj"].rank(pct=True) * 100
    df["supp_pct"] = df.groupby("grp")["supp"].rank(pct=True, ascending=False) * 100
    df["emp_Defense_pct"] = PADJ_W * df["padj_pct"] + SUPP_W * df["supp_pct"]
    # EA role percentiles within group
    for d in DIMS:
        df[f"ea_{d}_pct"] = df.groupby("grp")[f"ea_{d}"].rank(pct=True) * 100

    minutes = {"Attack": "att_min", "Possession": "att_min", "Defense": "def_min"}
    for d in DIMS:
        ea_pct, emp_pct = df[f"ea_{d}_pct"], df[f"emp_{d}_pct"]
        lam = np.minimum(df[minutes[d]] / SAT, 1.0) * CAP[d]
        lam = lam.where(emp_pct.notna(), 0.0)            # no empirical -> pure prior
        lam = lam.where(df["grp"].map(lambda g: d in RELEVANT.get(g, set())), 0.0)  # Option A off-role gate
        adj = (1 - lam) * ea_pct + lam * emp_pct
        adj = adj.where(ea_pct.notna(), emp_pct)          # no EA -> empirical only
        df[f"lam_{d}"] = lam
        df[f"adj_{d}"] = adj
        df[f"delta_{d}"] = adj - ea_pct
    return df


def report(df):
    print("CAPs:", CAP, "| SAT", SAT, "min | blend = (1-l)*EA + l*empirical (percentiles)\n")
    for d in DIMS:
        sub = df[df[f"ea_{d}_pct"].notna() & df[f"emp_{d}_pct"].notna()].copy()
        cols = ["name", "nat", "grp", f"ea_{d}_pct", f"emp_{d}_pct", f"lam_{d}", f"adj_{d}", f"delta_{d}"]
        fmt = {c: "{:.0f}".format for c in cols if c.endswith(("pct", f"adj_{d}", f"delta_{d}"))}
        fmt[f"lam_{d}"] = "{:.2f}".format
        print(f"================ {d} — EA most OVER-rated (empirical lower) ================")
        print(sub.sort_values(f"delta_{d}").head(8).to_string(index=False, columns=cols, formatters=fmt))
        print(f"---------------- {d} — EA most UNDER-rated (empirical higher) ----------------")
        print(sub.sort_values(f"delta_{d}", ascending=False).head(8).to_string(index=False, columns=cols, formatters=fmt))
        print()

    print("================ star profiles (adjusted pct per dimension) ================")
    stars = ["mohamed salah", "de bruyne", "haaland", "van dijk", "bellingham",
             "rodrigo de paul", "rudiger", "lautaro"]
    pc = ["name", "grp", "adj_Attack", "adj_Possession", "adj_Defense"]
    s = df[df["name"].str.contains("|".join(stars), na=False)].drop_duplicates("name")
    print(s.to_string(index=False, columns=pc, formatters={c: "{:.0f}".format for c in pc[2:]}))


def main() -> int:
    pd.set_option("display.width", 230)
    con = duckdb.connect(DB, read_only=True)
    df = build(con)
    con.close()
    report(df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
