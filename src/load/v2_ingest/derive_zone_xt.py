"""
derive_zone_xt.py  (chessboard item 1, part b — S32)

Empirical Expected Threat (xT) surface on the 30-zone board, estimated natively
from the StatsBomb international events (WC22/Euro24/Copa24/AFCON23).

Markov xT (Karun Singh):  xT(z) = s(z)*g(z) + m(z) * Sum_z' T(z->z') * xT(z')
solved by value iteration.  Each on-ball action in a zone is a SHOT or a MOVE:
    s(z) = shots / (shots + moves)        g(z) = goals / shots
    m(z) = 1 - s(z)                       T(z->z') from completed pass+carry
A TURNOVER (incomplete pass / dispossessed / miscontrol) ENDS possession at 0
value, so per zone: actions = moves + shots + turnovers, and m(z)=moves/actions
is strictly < 1. That possession-ending mass is what makes the value iteration
CONTRACT: without it, possession is immortal, m~1 with a row-stochastic T gives
spectral radius ~1, and the surface neither converges nor decays toward your own
goal (observed + fixed S32 — the absorbing state is load-bearing, not optional).

xT is team-AGNOSTIC (pool all teams): the generic value of the ball at z in
international football. Team-specific usage is a separate later layer.

Geometry: data/config/zone_grid.json. Design: docs/chessboard_design.md (item 1).
Output: zone_xt (30 rows), self-contained -> no FK.

    uv run python src/load/v2_ingest/derive_zone_xt.py            # dry-run, prints grid
    uv run python src/load/v2_ingest/derive_zone_xt.py --apply    # write zone_xt
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import duckdb, numpy as np

ROOT = Path(__file__).resolve().parents[3]
DB   = ROOT / "data" / "processed" / "worldcup.duckdb"
GRID = ROOT / "data" / "config" / "zone_grid.json"
MODEL_VERSION = "zone_xt_v1"


def load_grid():
    g = json.loads(GRID.read_text(encoding="utf-8"))
    band_cuts = g["bands"]["edges"][1:-1]      # interior x cut points -> 0..5
    lane_cuts = g["lanes"]["edges"]            # 4 interior y cut points -> 0..4
    n_bands = len(g["bands"]["edges"]) - 1
    n_lanes = len(g["lanes"]["edges"]) + 1
    return g, np.array(band_cuts), np.array(lane_cuts), n_bands, n_lanes


def zone_of(x, y, band_cuts, lane_cuts, n_lanes):
    band = np.digitize(np.asarray(x, float), band_cuts)   # 0..n_bands-1
    lane = np.digitize(np.asarray(y, float), lane_cuts)   # 0..n_lanes-1
    return band * n_lanes + lane


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--asymmetric", action="store_true",
                    help="disable L/R reflection symmetry (default: symmetric)")
    args = ap.parse_args()
    symmetric = not args.asymmetric
    print(f"mode: {'L/R-symmetric (reflection-augmented)' if symmetric else 'asymmetric (raw)'}")

    g, band_cuts, lane_cuts, n_bands, n_lanes = load_grid()
    Z = n_bands * n_lanes

    con = duckdb.connect(str(DB), read_only=not args.apply)
    mv = con.execute("""
        SELECT x, y, end_x, end_y FROM statsbomb_event
        WHERE ((type='Pass' AND outcome IS NULL) OR type='Carry')
          AND x IS NOT NULL AND y IS NOT NULL AND end_x IS NOT NULL AND end_y IS NOT NULL
    """).df()
    sh = con.execute("""
        SELECT x, y, outcome FROM statsbomb_event
        WHERE type='Shot' AND x IS NOT NULL AND y IS NOT NULL
    """).df()
    tv = con.execute("""
        SELECT x, y FROM statsbomb_event
        WHERE x IS NOT NULL AND y IS NOT NULL AND (
              (type='Pass' AND outcome IS NOT NULL)   -- incomplete / out / offside passes
              OR type IN ('Dispossessed', 'Miscontrol'))
    """).df()

    # --- counts per zone ---
    def mirror(za):                            # L<->R mirror of a zone array (lane reversed)
        return (za // n_lanes) * n_lanes + (n_lanes - 1 - za % n_lanes)

    oz = zone_of(mv.x, mv.y, band_cuts, lane_cuts, n_lanes)
    dz = zone_of(mv.end_x, mv.end_y, band_cuts, lane_cuts, n_lanes)
    sz = zone_of(sh.x, sh.y, band_cuts, lane_cuts, n_lanes)
    gz = sz[sh.outcome.values == "Goal"]
    tz = zone_of(tv.x, tv.y, band_cuts, lane_cuts, n_lanes)

    M = np.zeros((Z, Z))                       # transition counts
    np.add.at(M, (oz, dz), 1)
    shots = np.bincount(sz, minlength=Z).astype(float)
    goals = np.bincount(gz, minlength=Z).astype(float)
    turnovers = np.bincount(tz, minlength=Z).astype(float)   # possession-ending, 0 value
    if symmetric:
        # reflection augmentation: pool every event with its L<->R mirror (y->80-y),
        # so s,g,m,T and thus xT are left-right symmetric BY CONSTRUCTION (D1 prior;
        # removes footedness / small-sample / specific-player asymmetry, halves variance).
        np.add.at(M, (mirror(oz), mirror(dz)), 1)
        shots += np.bincount(mirror(sz), minlength=Z)
        goals += np.bincount(mirror(gz), minlength=Z)
        turnovers += np.bincount(mirror(tz), minlength=Z)
    moves = M.sum(1)                           # completed moves from each zone

    # --- per-zone probabilities (turnover mass = 1 - s - m, ends possession at 0) ---
    actions = moves + shots + turnovers
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(actions > 0, shots / actions, 0.0)         # P(shoot | action)
        m = np.where(actions > 0, moves / actions, 0.0)         # P(move  | action)
        gpr = np.where(shots > 0, goals / shots, 0.0)            # P(goal | shot)
        T = np.where(moves[:, None] > 0, M / np.where(moves[:, None] > 0, moves[:, None], 1), 0.0)

    # --- value iteration: xt = s*g + m * (T @ xt) ---
    sg = s * gpr
    xt = np.zeros(Z)
    for i in range(args.iters):
        nxt = sg + m * (T @ xt)
        if np.max(np.abs(nxt - xt)) < args.tol:
            break
        xt = nxt
    xt = nxt
    print(f"value iteration converged in {i+1} passes (max xT={xt.max():.4f})")

    # --- report: 6x5 grid, B6 (opp box) on top ---
    bn = g["bands"]["names"]; ln = g["lanes"]["names"]
    grid = xt.reshape(n_bands, n_lanes)
    print("\nxT surface (rows B6 opp-box -> B1 own-def; cols " + " ".join(ln) + ")")
    for b in range(n_bands - 1, -1, -1):
        print(f"  {bn[b]:11} " + "  ".join(f"{grid[b, l]:.4f}" for l in range(n_lanes)))
    band_mean = grid.mean(1)
    print("\nmean xT per band (must rise toward goal):")
    print("  " + "  ".join(f"{bn[b]}={band_mean[b]:.4f}" for b in range(n_bands)))
    mono = bool(np.all(np.diff(band_mean) > 0))
    peak = int(np.argmax(xt))
    print(f"monotonic toward goal: {mono}   peak zone={peak} "
          f"(band {peak//n_lanes+1}, lane {ln[peak % n_lanes]})  xT={xt[peak]:.4f}")
    if not mono or peak // n_lanes != n_bands - 1:
        print("  !! WARNING: surface does not match xT intuition — inspect before --apply")

    if not args.apply:
        print("\n(dry-run; pass --apply to write zone_xt)")
        con.close(); return

    con.execute("""CREATE OR REPLACE TABLE zone_xt (
        zone_id INTEGER PRIMARY KEY, band INTEGER, lane INTEGER,
        band_name VARCHAR, lane_name VARCHAR, xt DOUBLE,
        s DOUBLE, g DOUBLE, m DOUBLE, n_moves BIGINT, n_shots BIGINT, n_turnovers BIGINT,
        model_version VARCHAR, created_at TIMESTAMP DEFAULT now())""")
    for z in range(Z):
        b, l = z // n_lanes, z % n_lanes
        con.execute("INSERT INTO zone_xt (zone_id, band, lane, band_name, lane_name, "
                    "xt, s, g, m, n_moves, n_shots, n_turnovers, model_version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [z, b, l, bn[b], ln[l], float(xt[z]), float(s[z]), float(gpr[z]),
                     float(m[z]), int(moves[z]), int(shots[z]), int(turnovers[z]), MODEL_VERSION])
    n = con.execute("SELECT COUNT(*) FROM zone_xt").fetchone()[0]
    con.close()
    print(f"\nAPPLIED: zone_xt = {n} rows")


if __name__ == "__main__":
    main()
