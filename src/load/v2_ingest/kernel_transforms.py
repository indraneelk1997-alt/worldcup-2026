#!/usr/bin/env python3
"""
Item-4 SHIFT leg -- playstyle-axis -> occupancy kernel transforms.

Pure function `transform_kernel()` warps one position_code's two empirical
phase kernels (from occupancy_base) by a team's 5 blended playstyle axes
(from team_playstyle_blended) into a single occupancy kernel.

Design: docs/item4_kernel_transforms.md  (decision B: pure function, no table,
fired at formation-assembly time). No DB writes. The XI loop, lateral-fan rule,
and formation assembly live OUTSIDE this module and compose on top of it.

`--probe --nation ESP --code ST` prints before/after 6x5 grids to eyeball.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

import numpy as np
import duckdb

REPO = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO / "data" / "config" / "kernel_transforms.json"
DB_PATH = REPO / "data" / "processed" / "worldcup.duckdb"

N_BANDS, N_LANES, CENTER_LANE = 6, 5, 2
AXES = ("directness", "width", "line_height", "ppda", "possession")


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text())
    g = cfg["gains"]
    for k in ("LINE_GAIN", "PRESS_GAIN", "WIDTH_GAIN"):  # env override
        g[k] = float(os.environ.get(k, g[k]))
    cfg["fan_step"] = float(os.environ.get("FAN_STEP", cfg.get("fan_step", 1.0)))
    return cfg


def compute_forwardness(con) -> dict:
    """forwardness(code) = min-max of each code's DEFENCE-phase centroid band,
    derived live from occupancy_base so it never drifts from the data (single
    source of truth). FW -> 1.0, CB -> 0.0."""
    rows = con.execute(
        "SELECT position_code, SUM(weight*band)/SUM(weight) AS cband "
        "FROM occupancy_base WHERE phase='defence' GROUP BY position_code"
    ).fetchall()
    cb = {c: v for c, v in rows}
    lo, hi = min(cb.values()), max(cb.values())
    return {c: (v - lo) / (hi - lo) for c, v in cb.items()}


def load_kernel(con, code: str, phase: str):
    return con.execute(
        "SELECT band, lane, weight FROM occupancy_base "
        "WHERE position_code=? AND phase=?", [code, phase]
    ).fetchall()


def _splat(cells, pos_fn) -> np.ndarray:
    """Move each cell to a continuous target (b', l') = pos_fn(band, lane),
    clip to the board, and *bilinearly* spread its weight over the 4
    surrounding integer cells.

    Bilinear rather than round-to-nearest so a sub-band shift moves mass
    smoothly and conserves it exactly. Clipping caps the position at the
    edges, so mass pushed past the box accumulates on the edge band rather
    than falling off the board (then we renormalise upstream)."""
    grid = np.zeros((N_BANDS, N_LANES))
    for band, lane, w in cells:
        b, l = pos_fn(band, lane)
        b = min(max(b, 0.0), N_BANDS - 1)
        l = min(max(l, 0.0), N_LANES - 1)
        b0 = int(np.floor(b)); b1 = min(b0 + 1, N_BANDS - 1); fb = b - b0
        l0 = int(np.floor(l)); l1 = min(l0 + 1, N_LANES - 1); fl = l - l0
        grid[b0, l0] += w * (1 - fb) * (1 - fl)
        grid[b1, l0] += w * fb * (1 - fl)
        grid[b0, l1] += w * (1 - fb) * fl
        grid[b1, l1] += w * fb * fl
    return grid


def _cells_centroid(cells):
    tw = sum(w for _, _, w in cells)
    cb = sum(band * w for band, _, w in cells) / tw
    cl = sum(lane * w for _, lane, w in cells) / tw
    return cb, cl


def transform_kernel(attack, defence, axes: dict, gains: dict,
                     forwardness: float, fan_lane: float = 0.0,
                     attack_band_extra: float = 0.0,
                     defence_band_extra: float = 0.0,
                     spread: float = 0.0, availability: float = 1.0) -> np.ndarray:
    """Transformed 6x5 occupancy grid for ONE code; sums to `availability`
    (1.0 by default).

    attack/defence: lists of (band, lane, weight). axes: the 5 blended axes in
    [0,1] (0.5 = neutral). forwardness: scalar for this code.

    Team SHIFT (item 4): line translate (both phases), width lane stretch (both),
    press push (defence only), fan_lane (duplicated-central fan).
    Player TWEAK (item 5 Movement): attack_band_extra (Rapid/Quick Step, attack),
    defence_band_extra (Press Proven, defence), spread (Relentless dilation about
    the base centroid), availability (Relentless presence-budget boost). All fold
    into ONE resample per phase."""
    line_shift = gains["LINE_GAIN"] * (axes["line_height"] - 0.5)
    press_push = gains["PRESS_GAIN"] * (axes["ppda"] - 0.5) * forwardness
    width = gains["WIDTH_GAIN"] * (axes["width"] - 0.5)

    def make_pos(cells, band_shift):
        cb, cl = _cells_centroid(cells)          # spread dilates about BASE centroid
        def pos(band, lane):
            b = cb + (band - cb) * (1.0 + spread) + band_shift
            l = (cl + (lane - cl) * (1.0 + spread)     # Relentless dilation
                 + width * (lane - CENTER_LANE)        # team width (sign(d)*|d| == d)
                 + fan_lane)                           # formation fan
            return b, l
        return pos

    A = _splat(attack,  make_pos(attack,  line_shift + attack_band_extra))
    D = _splat(defence, make_pos(defence, line_shift + press_push + defence_band_extra))

    p = axes["possession"]                       # phase blend (outermost op)
    occ = p * A + (1.0 - p) * D
    s = occ.sum()
    occ = occ / s if s else occ                  # normalise to budget 1.0 ...
    return occ * availability                    # ... then apply the budget boost


# ---------- probe / display ----------

def _centroid_band(grid) -> float:
    bands = np.arange(N_BANDS)[:, None]
    return float((grid * bands).sum() / grid.sum())


def _centroid_lane(grid) -> float:
    lanes = np.arange(N_LANES)[None, :]
    return float((grid * lanes).sum() / grid.sum())


def _fmt_grid(grid, title) -> str:
    lanes = ["LW", "LH", "C", "RH", "RW"]           # opp box on top, own box bottom
    out = [title, "       " + "".join(f"{x:>6}" for x in lanes)]
    for b in range(N_BANDS - 1, -1, -1):
        cells = "".join(f"{grid[b, l] * 100:6.1f}" for l in range(N_LANES))
        out.append(f"  B{b + 1} |{cells}")
    out.append(f"  centroid band={_centroid_band(grid):.3f}  "
               f"lane={_centroid_lane(grid):.3f}  sum={grid.sum() * 100:.1f}%")
    return "\n".join(out)


def probe(nation: str, code: str, attack_band_extra=0.0, defence_band_extra=0.0,
          spread=0.0, availability=1.0):
    cfg = load_config()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    fwd = compute_forwardness(con)
    row = con.execute(
        f"SELECT {', '.join(AXES)} FROM team_playstyle_blended WHERE nation_fifa3=?",
        [nation]).fetchone()
    if row is None:
        raise SystemExit(f"no team_playstyle_blended row for nation {nation!r}")
    axes = dict(zip(AXES, row))
    attack, defence = load_kernel(con, code, "attack"), load_kernel(con, code, "defence")
    if not attack or not defence:
        raise SystemExit(f"no occupancy_base kernel for code {code!r}")

    ident = lambda b, l: (b, l)
    base_a, base_d = _splat(attack, ident), _splat(defence, ident)
    out = transform_kernel(attack, defence, axes, cfg["gains"], fwd[code],
                           attack_band_extra=attack_band_extra,
                           defence_band_extra=defence_band_extra,
                           spread=spread, availability=availability)

    g = cfg["gains"]
    print(f"== {nation} / {code} ==  forwardness={fwd[code]:.3f}  gains={g}")
    print("axes: " + ", ".join(f"{a}={axes[a]:.3f}" for a in AXES))
    print(f"line_shift={g['LINE_GAIN'] * (axes['line_height'] - 0.5):+.3f}  "
          f"press_push={g['PRESS_GAIN'] * (axes['ppda'] - 0.5) * fwd[code]:+.3f}  "
          f"| TWEAK atk_band={attack_band_extra:+.2f} def_band={defence_band_extra:+.2f} "
          f"spread={spread:+.2f} avail={availability:.2f}\n")
    print(_fmt_grid(base_a, "BASE attack:"), "\n")
    print(_fmt_grid(base_d, "BASE defence:"), "\n")
    print(_fmt_grid(out, "TRANSFORMED (possession-blended):"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--nation", default="ESP")
    ap.add_argument("--code", default="ST")
    ap.add_argument("--atk-band", type=float, default=0.0)   # Rapid / Quick Step
    ap.add_argument("--def-band", type=float, default=0.0)   # Press Proven
    ap.add_argument("--spread", type=float, default=0.0)     # Relentless dilation
    ap.add_argument("--avail", type=float, default=1.0)      # Relentless budget
    a = ap.parse_args()
    if a.probe:
        probe(a.nation, a.code, attack_band_extra=a.atk_band,
              defence_band_extra=a.def_band, spread=a.spread, availability=a.avail)
    else:
        print("nothing to do; try: --probe --nation URU --code ST")


if __name__ == "__main__":
    main()
