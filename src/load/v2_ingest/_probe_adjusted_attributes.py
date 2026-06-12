"""
_probe_adjusted_attributes.py — S28 (deletable). Map the locked per-dimension
form blend DOWN onto individual EA sub-attributes (discriminators only, uniform
additive shift), per docs/blend_redesign.md "Attribute-level mapping".

Reuses _probe_adjusted_ratings.build() for the per-player ea_<dim> role rating +
adj_<dim> blended percentile (within position group). Then, per dimension d:
  adj_rating_d  = invert adj_pct_d against the GROUP's raw EA role-rating dist
  delta_role_d  = adj_rating_d - raw_ea_role_d
  s_d           = delta_role_d / BASE_W      # role = 0.75*base + 0.25*bonus;
                  bonus held fixed, so a uniform shift s on the base discriminators
                  moves the role rating by 0.75*s -> invert to hit delta_role_d
  adj_attr_i    = clip(raw_attr_i + s_d, 1, 99)   for each discriminator i of dim d

IMPL NOTE being observed (blend_redesign.md): whether to define the target on the
role composite (this version) or on the base alone, and the s = delta/BASE_W
factor. We PRINT role/base/s side by side so the maintainer can sanity-check the
numbers before the mapping is committed to the real engine.

Read-only.  uv run python src/load/v2_ingest/_probe_adjusted_attributes.py
"""
from __future__ import annotations

import sys

import duckdb
import numpy as np
import pandas as pd

import _ea_attribute_buckets as eab
import _probe_adjusted_ratings as eng

DB = "data/processed/worldcup.duckdb"
DIMS = ["Attack", "Possession", "Defense"]
DISC = {"Attack": eab.ATTACK, "Possession": eab.POSSESSION, "Defense": eab.DEFENSE}
STARS = ["mohamed salah", "de bruyne", "haaland", "van dijk", "rodrigo de paul", "rudiger"]


def invert_pct(group_ratings: pd.Series, pct: float) -> float:
    """Rating at a within-group percentile — the inverse of rank(pct=True)*100.
    np.percentile convention; close-but-not-identical to pandas rank, flagged as a
    known approximation to tighten once the shape is agreed."""
    vals = group_ratings.dropna().to_numpy()
    if len(vals) == 0 or pd.isna(pct):
        return np.nan
    return float(np.percentile(vals, pct))


def main() -> int:
    pd.set_option("display.width", 230)
    con = duckdb.connect(DB, read_only=True)
    df = eng.build(con)                                   # name(=name_norm), grp, ea_<d>, ea_<d>_pct, adj_<d>
    sq = con.sql("SELECT name_norm, ea_id FROM wc2026_squad WHERE ea_id IS NOT NULL").df()
    ea = con.sql(f"SELECT {', '.join(['ea_id'] + eab.ALL_ATTRS)} FROM ea_fc26_player").df()
    con.close()

    df = (df.merge(sq, left_on="name", right_on="name_norm", how="left")
            .merge(ea, on="ea_id", how="left"))

    # per dimension: invert adj_pct within group -> adjusted role rating -> delta -> s
    for d in DIMS:
        adjR = [invert_pct(df.loc[df["grp"] == r["grp"], f"ea_{d}"], r[f"adj_{d}"])
                for _, r in df.iterrows()]
        df[f"adjR_{d}"] = adjR
        df[f"s_{d}"] = (df[f"adjR_{d}"] - df[f"ea_{d}"]) / eab.BASE_W
        df[f"s_{d}"] = df[f"s_{d}"].where(df[f"lam_{d}"] > 0, 0.0)  # off-role / no-emp -> exactly no shift

    sub = df[df["name"].str.contains("|".join(STARS), na=False)].drop_duplicates("name")
    if sub.empty:
        print("no star rows matched — check name_norm watchlist")
        return 1
    for _, r in sub.iterrows():
        print(f"\n================ {r['name']}  ({r['grp']}) ================")
        for d in DIMS:
            s = r[f"s_{d}"]
            if pd.isna(s):
                print(f"  {d}: ea_pct={r[f'ea_{d}_pct']:.0f}  (no empirical -> no shift)")
                continue
            print(f"  {d}: ea_pct {r[f'ea_{d}_pct']:.0f} -> adj_pct {r[f'adj_{d}']:.0f} | "
                  f"role {r[f'ea_{d}']:.1f} -> {r[f'adjR_{d}']:.1f}  (shift s = {s:+.1f})")
            for a in DISC[d]:
                raw = r[a]
                new = float(np.clip(raw + s, 1, 99))
                flag = "  <clip" if (raw + s < 1 or raw + s > 99) else ""
                print(f"      {a:<18} {raw:>4.0f} -> {new:>4.0f}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
