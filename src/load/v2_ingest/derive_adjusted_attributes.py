"""
derive_adjusted_attributes.py — S29. Persist the S28 form->sub-attribute mapping
(designed in docs/blend_redesign.md, prototyped in _probe_adjusted_attributes) as
a DERIVED table the chessboard consumes:

  player_adjusted_attributes        (long: one row per player x attribute)
  player_adjusted_attributes_wide   (one row per player; PIVOT of adj)

Mapping recap: each player's EA discriminator sub-attributes are shifted by their
dimension form percentile (uniform, s = delta / BASE_W); bonus attrs
(Skills/IQ/Physical) stay at raw EA. Off-role dims gated to lam=0 (Option A), so
their attributes get shift_s=0. adj stored CONTINUOUS (not rounded to EA ints).

DERIVED -> --apply does a wholesale CREATE OR REPLACE rebuild (idempotent, safe;
self-contained on its own grain, no FK-block exposure). Dry-run (default) computes
everything and prints a summary + sample but writes nothing. v1 scope: EA-present
players only (ea_id NOT NULL); GKs excluded (separate track, dropped upstream in
build()); dark-player position-average fallback deferred.

    uv run python src/load/v2_ingest/derive_adjusted_attributes.py            # dry-run
    uv run python src/load/v2_ingest/derive_adjusted_attributes.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

import _ea_attribute_buckets as eab
import _probe_adjusted_ratings as eng          # the (permanent) blend engine: build()

DB = "data/processed/worldcup.duckdb"
DIMS = ["Attack", "Possession", "Defense"]
DISC = {"Attack": eab.ATTACK, "Possession": eab.POSSESSION, "Defense": eab.DEFENSE}
MODEL_VERSION = "adj_attr_v1"

BUCKET = {a: b for b, attrs in [
    ("Attack", eab.ATTACK), ("Possession", eab.POSSESSION), ("Defense", eab.DEFENSE),
    ("Skills", eab.SKILLS), ("IQ", eab.IQ), ("Physical", eab.PHYSICAL)] for a in attrs}
ATTR_DIM = {a: d for d in DIMS for a in DISC[d]}    # discriminator attr -> its role dim


def invert_pct(group_ratings: pd.Series, pct: float) -> float:
    """Rating at a within-group percentile — inverse of rank(pct=True)*100.
    np.percentile convention (small approximation vs pandas rank; flagged v2)."""
    vals = group_ratings.dropna().to_numpy()
    if len(vals) == 0 or pd.isna(pct):
        return np.nan
    return float(np.percentile(vals, pct))


def build_long(con) -> pd.DataFrame:
    df = eng.build(con)            # squad_row_id, ea_id, grp, ea_<d>, ea_<d>_pct, adj_<d>, lam_<d>
    ea = con.sql(f"SELECT {', '.join(['ea_id'] + eab.ALL_ATTRS)} FROM ea_fc26_player").df()
    df = df.merge(ea, on="ea_id", how="left")
    df = df[df["ea_id"].notna()].copy()                      # EA-present only (v1 scope)

    for d in DIMS:                                           # dim form pct -> shift s (gated by lam>0)
        adjR = pd.Series(
            [invert_pct(df.loc[df["grp"] == r["grp"], f"ea_{d}"], r[f"adj_{d}"])
             for _, r in df.iterrows()], index=df.index)
        df[f"s_{d}"] = ((adjR - df[f"ea_{d}"]) / eab.BASE_W).where(df[f"lam_{d}"] > 0, 0.0)

    now = datetime.now()
    out = []
    for _, r in df.iterrows():
        for a in eab.ALL_ATTRS:
            if pd.isna(r[a]):
                continue
            d = ATTR_DIM.get(a)                              # None for bonus attrs
            ea_raw = float(r[a])
            s = float(r[f"s_{d}"]) if d is not None else 0.0
            out.append({
                "squad_row_id": int(r["squad_row_id"]),
                "ea_id": int(r["ea_id"]),
                "position_group": r["grp"],
                "attribute": a,
                "bucket": BUCKET[a],
                "is_discriminator": d is not None,
                "ea_raw": ea_raw,
                "shift_s": s,
                "adj": float(np.clip(ea_raw + s, 1, 99)),
                "adj_pct": float(r[f"adj_{d}"]) if d is not None else None,
                "lambda_dim": float(r[f"lam_{d}"]) if d is not None else None,
                "model_version": MODEL_VERSION,
                "created_at": now,
            })
    return pd.DataFrame(out)


DDL = """
CREATE OR REPLACE TABLE player_adjusted_attributes (
    squad_row_id     BIGINT  NOT NULL,
    ea_id            BIGINT,
    position_group   VARCHAR,
    attribute        VARCHAR NOT NULL,
    bucket           VARCHAR,
    is_discriminator BOOLEAN,
    ea_raw           DOUBLE,
    shift_s          DOUBLE,
    adj              DOUBLE,
    adj_pct          DOUBLE,
    lambda_dim       DOUBLE,
    model_version    VARCHAR,
    created_at       TIMESTAMP,
    PRIMARY KEY (squad_row_id, attribute)
);
"""
# wide = materialized table (rebuilt alongside long, so no drift). NOT a view:
# DuckDB PIVOT has dynamic columns, unreliable inside CREATE VIEW; CTAS is safe.
WIDE = ("CREATE OR REPLACE TABLE player_adjusted_attributes_wide AS "
        "PIVOT player_adjusted_attributes ON attribute USING max(adj) GROUP BY squad_row_id")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    con = duckdb.connect(DB, read_only=not args.apply)
    long = build_long(con)

    n_players = long["squad_row_id"].nunique()
    print(f"rows={len(long)}  players={n_players}  attrs/player≈{len(long) / max(n_players, 1):.1f}")
    print(f"discriminator rows shifted (|s|>0): {(long['shift_s'].abs() > 1e-9).sum()}  "
          f"of {long['is_discriminator'].sum()} discriminator rows")
    print(long.groupby("bucket")["shift_s"].agg(["count", "mean", "min", "max"]).round(2))
    samp = con.sql("SELECT squad_row_id FROM wc2026_squad "
                   "WHERE name_norm LIKE '%van dijk%' OR name_norm LIKE '%mohamed salah%'").df()
    ids = set(samp["squad_row_id"].tolist())
    show = long[long["squad_row_id"].isin(ids) & long["is_discriminator"]]
    print("\nsample (Van Dijk + Salah, discriminators):")
    print(show[["squad_row_id", "attribute", "bucket", "ea_raw", "shift_s", "adj"]].to_string(index=False))

    if not args.apply:
        print("\n[dry-run] no writes. Re-run with --apply to rebuild table + wide.")
        con.close()
        return 0

    con.execute(DDL)
    con.register("long_df", long)
    con.execute("INSERT INTO player_adjusted_attributes BY NAME SELECT * FROM long_df")
    con.execute(WIDE)
    n = con.sql("SELECT count(*) FROM player_adjusted_attributes").fetchone()[0]
    w = con.sql("SELECT count(*) FROM player_adjusted_attributes_wide").fetchone()[0]
    print(f"\n[apply] player_adjusted_attributes: {n} rows; wide: {w} players. Rebuilt.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
