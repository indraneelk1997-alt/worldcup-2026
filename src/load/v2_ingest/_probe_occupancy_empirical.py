"""
_probe_occupancy_empirical.py  (S32, DELETABLE — exploratory)

Can we derive item-3 occupancy kernels straight from StatsBomb instead of
hand-authoring role templates? For a few representative positions, show the
empirical zone distribution of (a) ON-BALL events ~ attack-phase occupancy and
(b) DEFENSIVE actions ~ defence-phase occupancy. Each event is in the acting
team's own attack-+x frame, so a position's own occupancy is clean (no cross-team
mixing). Read-only.

    uv run python src/load/v2_ingest/_probe_occupancy_empirical.py
"""
from __future__ import annotations
import duckdb, numpy as np
from derive_zone_xt import load_grid, zone_of, DB

g, band_cuts, lane_cuts, n_bands, n_lanes = load_grid()
Z = n_bands * n_lanes
LN = g["lanes"]["names"]

POSITIONS = ["Left Center Back", "Left Back", "Center Defensive Midfield",
             "Left Wing", "Center Forward"]
ONBALL = ("Pass", "Carry", "Ball Receipt*", "Dribble", "Shot")
DEFACT = ("Pressure", "Duel", "Interception", "Block", "Clearance",
          "Ball Recovery", "Foul Committed")


def grid_print(title, vec, n):
    m = (vec / max(vec.sum(), 1)).reshape(n_bands, n_lanes)
    print(f"  {title} (n={n})  rows B6->B1, cols {' '.join(LN)}")
    for b in range(n_bands - 1, -1, -1):
        print("    " + "  ".join(f"{m[b,l]*100:4.1f}" for l in range(n_lanes)))


def main():
    con = duckdb.connect(str(DB), read_only=True)
    for pos in POSITIONS:
        print(f"\n=== {pos} ===")
        for label, types in (("ON-BALL  (attack occ.)", ONBALL),
                             ("DEFENSIVE(defence occ.)", DEFACT)):
            tl = "','".join(types)
            df = con.execute(f"""
                SELECT x, y FROM statsbomb_event
                WHERE position = ? AND type IN ('{tl}')
                  AND x IS NOT NULL AND y IS NOT NULL
            """, [pos]).df()
            zc = zone_of(df.x, df.y, band_cuts, lane_cuts, n_lanes)
            vec = np.bincount(zc, minlength=Z).astype(float)
            grid_print(label, vec, len(df))
    con.close()


if __name__ == "__main__":
    main()
