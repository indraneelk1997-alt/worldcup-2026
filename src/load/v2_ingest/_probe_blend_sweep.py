"""
_probe_blend_sweep.py  (S32, DELETABLE)

Compare D2 blend settings from baseline to minimal-shrinkage, to pick the
trust/shrinkage knobs before --apply. Imports blend() from the deriver so the
math is identical (no drift). Read-only.

    uv run python src/load/v2_ingest/_probe_blend_sweep.py
"""
from __future__ import annotations
import duckdb
from derive_team_playstyle_blended import Params, load_inputs, blend, DB, AXES

# baseline -> progressively less shrinkage (higher lambda_max, lower tau, more WC22 credit)
SETTINGS = {
    "S0 baseline": Params(rho_wc22=0.5, m0=4.0, lambda_max=0.7,  tau=0.5),
    "S1 moderate": Params(rho_wc22=0.7, m0=4.0, lambda_max=0.8,  tau=0.4),
    "S2 low":      Params(rho_wc22=0.8, m0=3.0, lambda_max=0.9,  tau=0.3),
    "S2b chosen":  Params(rho_wc22=0.8, m0=3.0, lambda_max=0.9,  tau=0.4),
    "S3 minimal":  Params(rho_wc22=0.9, m0=3.0, lambda_max=0.95, tau=0.25),
}

# representative: elite well-covered (n=2) | thin or coach-changed | a dark side (unchanged)
SHOW = ["Spain", "Argentina", "France", "Germany", "Portugal", "Uruguay",
        "Qatar", "Japan", "Iran", "Norway"]


def personality(out, subset=None) -> float:
    """Mean over sides of mean-axis |blend - prior| (higher = more identity, less shrinkage)."""
    rows = [r for r in out if r["emp"] and (subset is None or r["n"] in subset)]
    if not rows:
        return 0.0
    per = [sum(abs(r["blend"][i] - r["prior"][i]) for i in range(len(AXES))) / len(AXES) for r in rows]
    return sum(per) / len(per)


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    rows, cfgs = load_inputs(con)
    con.close()
    results = {name: {r["name"]: r for r in blend(rows, cfgs, p)} for name, p in SETTINGS.items()}

    # --- lambda_team per representative side across settings ---
    print(f"\nlambda_team by setting")
    print(f"{'nation':14} " + "  ".join(f"{s:>11}" for s in SETTINGS))
    for nm in SHOW:
        cells = "  ".join(f"{results[s][nm]['lam']:>11.2f}" for s in SETTINGS)
        print(f"{nm:14} {cells}")

    # --- Spain possession & line height: watch them climb toward empirical ---
    sp_emp = results["S0 baseline"]["Spain"]["emp"]
    print(f"\nSpain  (empirical possession={sp_emp[4]:.3f}, line={sp_emp[2]:.3f})")
    print(f"{'axis':10} " + "  ".join(f"{s:>11}" for s in SETTINGS))
    for ax, idx in [("possession", 4), ("line_height", 2), ("directness", 0)]:
        cells = "  ".join(f"{results[s]['Spain']['blend'][idx]:>11.3f}" for s in SETTINGS)
        print(f"{ax:10} {cells}")

    # --- global "personality" / shrinkage summary ---
    print(f"\npersonality = mean |blend - prior| (higher = sides further from prior)")
    print(f"{'subset':16} " + "  ".join(f"{s:>11}" for s in SETTINGS))
    for label, subset in [("all 39 blended", None), ("well-covered n=2", {2}), ("single-row n=1", {1})]:
        cells = "  ".join(f"{personality(list(results[s].values()), subset):>11.3f}" for s in SETTINGS)
        print(f"{label:16} {cells}")

    # mean lambda over the 39
    print(f"\nmean lambda_team over 39 blended sides")
    for s in SETTINGS:
        lams = [r["lam"] for r in results[s].values() if r["emp"]]
        print(f"  {s:14} {sum(lams)/len(lams):.3f}")


if __name__ == "__main__":
    main()
