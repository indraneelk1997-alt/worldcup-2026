"""
derive_occupancy_base.py  (chessboard item 3 — S32)

Empirical BASE occupancy kernels per (position_code, phase) on the 30-zone board,
from StatsBomb international events. Realises D4 (occupancy = a spread kernel,
presence budget 1.0) and the empirical leg of D5 (two phases) at once:
  - ATTACK  phase = on-ball events     (where the player operates WITH the ball)
  - DEFENCE phase = defensive actions  (where they are WITHOUT it)

Each event is in the acting team's own attack-+x frame, so a position's occupancy
is clean. Kernels are mirror-symmetrised (L<->R, D1 prior), set-pieces excluded
(open play only), normalised to budget 1.0, truncated to the meaningful territory,
and tiered (home/primary/secondary/tertiary = weight bands, readable slicing).

Config: data/config/occupancy_events.json + data/config/zone_grid.json.
Design: docs/chessboard_design.md (D4/D5, item 3). Output: occupancy_base
(self-contained on code+zone -> no FK).

    uv run python src/load/v2_ingest/derive_occupancy_base.py            # dry-run, prints kernels
    uv run python src/load/v2_ingest/derive_occupancy_base.py --apply    # write occupancy_base
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import duckdb, numpy as np
from derive_zone_xt import load_grid, zone_of, DB

CFG = Path(__file__).resolve().parents[3] / "data" / "config" / "occupancy_events.json"
MODEL_VERSION = "occupancy_base_v1"
MIN_W = 0.03          # truncate cells below 3% of budget, then renormalise (-> ~territory)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min_w", type=float, default=MIN_W)
    ap.add_argument("--show", default="LCB,LW,ST,DM", help="codes to print in dry-run")
    args = ap.parse_args()

    g, band_cuts, lane_cuts, n_bands, n_lanes = load_grid()
    Z = n_bands * n_lanes
    LN, BN = g["lanes"]["names"], g["bands"]["names"]
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    phases, pairs = cfg["phases"], cfg["mirror_pairs"]
    code_sb, setp = cfg["code_sb_positions"], cfg["set_piece_play_patterns"]
    right_of = pairs                          # left -> right
    left_of = {r: l for l, r in pairs.items()}

    def mirror(v):                            # L<->R reflection of a 30-vector
        return v.reshape(n_bands, n_lanes)[:, ::-1].reshape(-1)

    con = duckdb.connect(str(DB), read_only=not args.apply)

    def raw_hist(code, phase):                # set-piece-excluded zone histogram
        pl = "','".join(code_sb[code]); tl = "','".join(phases[phase]); sp = "','".join(setp)
        df = con.execute(f"""
            SELECT x, y FROM statsbomb_event
            WHERE position IN ('{pl}') AND type IN ('{tl}')
              AND x IS NOT NULL AND y IS NOT NULL
              AND (play_pattern IS NULL OR play_pattern NOT IN ('{sp}'))
        """).df()
        zc = zone_of(df.x, df.y, band_cuts, lane_cuts, n_lanes)
        return np.bincount(zc, minlength=Z).astype(float), len(df)

    # raw histograms (skip GK)
    codes = [c for c in code_sb if c != "GK"]
    raw, nev = {}, {}
    for c in codes:
        for ph in phases:
            raw[(c, ph)], nev[(c, ph)] = raw_hist(c, ph)

    # symmetrise: left = self + mirror(right partner); right = mirror(left); central = self+mirror(self)
    def kernel(code, ph):
        if code in right_of:                  # left code with a right partner
            h = raw[(code, ph)] + mirror(raw[(right_of[code], ph)])
        elif code in left_of:                 # right code -> mirror of its left
            return mirror(kernel(left_of[code], ph))
        else:                                 # central / self-symmetric
            h = raw[(code, ph)] + mirror(raw[(code, ph)])
        s = h.sum()
        return h / s if s else h

    def truncate_tier(v):                     # -> {zone: (weight, tier)}
        w = np.where(v >= args.min_w, v, 0.0)
        s = w.sum()
        if s == 0:
            return {}
        w = w / s
        mx = w.max()
        out = {}
        for z in np.nonzero(w)[0]:
            wt = w[z]
            tier = ("home" if wt == mx else "primary" if wt >= 0.5 * mx
                    else "secondary" if wt >= 0.25 * mx else "tertiary")
            out[int(z)] = (float(wt), tier)
        return out

    results = {(c, ph): truncate_tier(kernel(c, ph)) for c in codes for ph in phases}

    # ---- dry-run report ----
    def grid(cells):
        m = np.zeros((n_bands, n_lanes))
        for z, (wt, _) in cells.items():
            m[z // n_lanes, z % n_lanes] = wt
        return m

    for code in [c.strip() for c in args.show.split(",") if c.strip() in codes]:
        for ph in phases:
            cells = results[(code, ph)]
            m = grid(cells)
            print(f"\n{code} · {ph}  (n={nev[(code,ph)]}, {len(cells)} cells, Σ={sum(w for w,_ in cells.values()):.2f})")
            for b in range(n_bands - 1, -1, -1):
                print("   " + "  ".join(f"{m[b,l]*100:4.1f}" if m[b,l] else "  . " for l in range(n_lanes)))
    # symmetry self-check on a central code
    dmA = grid(results[("DM", "attack")])
    print(f"\nsymmetry check (DM attack, |L-R| max) = {np.abs(dmA - dmA[:, ::-1]).max():.2e}")
    sizes = [len(results[(c, ph)]) for c in codes for ph in phases]
    print(f"kernels: {len(codes)} codes × 2 phases; cells/kernel min={min(sizes)} median={int(np.median(sizes))} max={max(sizes)}")

    if not args.apply:
        print("\n(dry-run; pass --apply to write occupancy_base)")
        con.close(); return

    con.execute("""CREATE OR REPLACE TABLE occupancy_base (
        position_code VARCHAR, phase VARCHAR, zone_id INTEGER, band INTEGER, lane INTEGER,
        weight DOUBLE, tier VARCHAR, n_events INTEGER,
        model_version VARCHAR, created_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (position_code, phase, zone_id))""")
    rows = 0
    for c in codes:
        for ph in phases:
            for z, (wt, tier) in results[(c, ph)].items():
                con.execute("INSERT INTO occupancy_base (position_code, phase, zone_id, band, lane, "
                            "weight, tier, n_events, model_version) VALUES (?,?,?,?,?,?,?,?,?)",
                            [c, ph, z, z // n_lanes, z % n_lanes, wt, tier, nev[(c, ph)], MODEL_VERSION])
                rows += 1
    n = con.execute("SELECT COUNT(*) FROM occupancy_base").fetchone()[0]
    con.close()
    print(f"\nAPPLIED: occupancy_base = {n} rows ({len(codes)} codes × 2 phases)")


if __name__ == "__main__":
    main()
