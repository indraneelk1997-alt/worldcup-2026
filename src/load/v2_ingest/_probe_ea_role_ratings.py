"""
_probe_ea_role_ratings.py — S27 probe (deletable). Validate the EA role-rating
decomposition (_ea_attribute_buckets): does Attack/Holding/Defense rank the
archetypes sensibly, and are the top players per role the right kind? Read-only.

    uv run python src/load/v2_ingest/_probe_ea_role_ratings.py
"""
from __future__ import annotations

import sys

import duckdb
import pandas as pd

import _ea_attribute_buckets as b

DB = "data/processed/worldcup.duckdb"


def main() -> int:
    pd.set_option("display.width", 200)
    con = duckdb.connect(DB, read_only=True)
    cols = ", ".join(["ea_id", "name", "position", "ovr"] + b.ALL_ATTRS)
    ea = con.sql(f"SELECT {cols} FROM ea_fc26_player").df()
    con.close()

    ea = b.add_ratings(ea)
    r3 = ["Attack", "Holding", "Defense"]
    ea["top_role"] = ea[r3].idxmax(axis=1)

    print("=== ARCHETYPE check (bases | bonuses | role ratings | top) ===")
    arche = ["Erling Haaland", "Mohamed Salah", "Kevin De Bruyne",
             "Declan Rice", "Virgil van Dijk"]
    cols_show = ["name", "position", "AttackBase", "HoldingBase", "DefenseBase",
                 "Skills", "IQ", "Physical", "Attack", "Holding", "Defense", "top_role"]
    a = ea[ea["name"].str.contains("|".join(arche), case=False, na=False)].drop_duplicates("name")
    print(a[cols_show].round(1).to_string(index=False))

    out = ea[ea["position"] != "GK"]
    for role in r3:
        print(f"\n=== top 8 by EA {role} (outfield) ===")
        print(out.sort_values(role, ascending=False).head(8)[
            ["name", "position", role, "Attack", "Holding", "Defense"]].round(1).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
