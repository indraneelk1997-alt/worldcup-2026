"""
derive_team_playstyle_blended.py  (D2 prior leg + blend, S32)

Combine the empirical playstyle leg (team_playstyle_empirical, S31) with a
confederation-mean prior into one current-2026 5-axis playstyle vector per
WC2026 nation.

    axis_2026 = (1 - lambda_team) * prior + lambda_team * empirical_vec

Design + rationale: docs/d2_prior_blend_design.md  (read it before editing).
Configs:
    data/config/nation_codes.json            SB-name/nation -> FIFA-3 (qualifier filter)
    data/config/statsbomb_team_aliases.json  3 non-exact SB strings -> nation name
    data/config/coach_continuity.json         per (nation|tournament) continuity
    data/config/confederations.json           nation/SB-string -> confederation

The blend math lives in one function, blend(), so the sweep probe
(_probe_blend_sweep.py) and this deriver compute identically (no drift).

Tunables are env-overridable (S28 CAP precedent) for tuning without code edits:
    BLEND_RHO_WC22  recency weight for WC22       (default 0.8; 2024 tourneys = 1.0)
    BLEND_M0        volume saturation midpoint     (default 3.0; vol = m/(m+M0))
    BLEND_LAMBDA_MAX  cap on empirical trust       (default 0.9)
    BLEND_TAU       evidence scale                 (default 0.4)

Usage:
    uv run python src/load/v2_ingest/derive_team_playstyle_blended.py            # dry-run
    BLEND_LAMBDA_MAX=0.8 BLEND_TAU=0.4 uv run python .../derive_team_playstyle_blended.py
    uv run python src/load/v2_ingest/derive_team_playstyle_blended.py --apply    # write table
"""
from __future__ import annotations
import argparse, json, math, os
from collections import namedtuple
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[3]
DB   = ROOT / "data" / "processed" / "worldcup.duckdb"
CFG  = ROOT / "data" / "config"
MODEL_VERSION = "playstyle_blended_v1"

AXES = ["directness", "width", "line_height", "ppda", "possession"]
NORM_COLS = [a + "_norm" for a in AXES]

# (competition_id, season_id) -> tournament code
TOURNAMENT = {(43, 106): "wc2022", (55, 282): "euro2024",
              (223, 282): "copa2024", (1267, 107): "afcon2023"}

Params = namedtuple("Params", "rho_wc22 m0 lambda_max tau")


def env_params() -> Params:
    # Defaults = "S2b" locked S32 (less shrinkage: tournament football expresses
    # identity). lambda_max=0.9 lets well-covered sides move off the prior;
    # tau=0.4 keeps the curve separating well-covered (~0.80-0.86) from thin/
    # coach-changed (~0.35) sides. See docs/d2_prior_blend_design.md.
    g = lambda k, d: float(os.environ.get(k, d))
    return Params(g("BLEND_RHO_WC22", 0.8), g("BLEND_M0", 3.0),
                  g("BLEND_LAMBDA_MAX", 0.9), g("BLEND_TAU", 0.4))


def load_cfg(name: str) -> dict:
    d = json.loads((CFG / name).read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_inputs(con) -> tuple[list, dict]:
    rows = con.execute(
        f"SELECT team, team_id, competition_id, season_id, n_matches, "
        f"{', '.join(NORM_COLS)} FROM team_playstyle_empirical"
    ).fetchall()
    cfgs = dict(
        nat=load_cfg("nation_codes.json"),
        ali=load_cfg("statsbomb_team_aliases.json"),
        conf=load_cfg("confederations.json"),
        cont=json.loads((CFG / "coach_continuity.json").read_text(encoding="utf-8"))["rows"],
    )
    return rows, cfgs


def blend(rows: list, cfgs: dict, p: Params) -> list[dict]:
    """Pure function: empirical rows + configs + params -> 48 blended nation dicts."""
    nat, ali, conf, cont = cfgs["nat"], cfgs["ali"], cfgs["conf"], cfgs["cont"]
    k = len(AXES)

    # 1. annotate every empirical row
    recs = []
    for team, team_id, comp, seas, n_matches, *vec in rows:
        tcode = TOURNAMENT[(comp, seas)]
        recency = p.rho_wc22 if tcode == "wc2022" else 1.0
        name = ali.get(team, team)
        fifa3 = nat.get(name)
        volume = n_matches / (n_matches + p.m0)
        c = cont.get(f"{name}|{tcode}", {}).get("continuity", 1.0) if fifa3 else 1.0
        recs.append(dict(team=team, name=name, fifa3=fifa3, confed=conf[name],
                         evidence=recency * volume * c, vec=[float(x) for x in vec]))

    # 2. confederation-mean prior (equal weight per team, then per confederation)
    by_team, team_confed = {}, {}
    for r in recs:
        by_team.setdefault(r["team"], []).append(r["vec"])
        team_confed[r["team"]] = r["confed"]
    team_vec = {t: [sum(c) / len(vs) for c in zip(*vs)] for t, vs in by_team.items()}
    confed_teams = {}
    for t, cf in team_confed.items():
        confed_teams.setdefault(cf, []).append(t)
    confed_prior = {cf: [sum(c) / len(ts) for c in zip(*[team_vec[t] for t in ts])]
                    for cf, ts in confed_teams.items()}
    global_prior = [sum(c) / len(team_vec) for c in zip(*team_vec.values())]

    # 3. per-nation evidence-weighted empirical combine
    nat_rows = {}
    for r in recs:
        if r["fifa3"]:
            nat_rows.setdefault(r["fifa3"], []).append(r)
    emp = {}
    for fifa3, rs in nat_rows.items():
        E = sum(r["evidence"] for r in rs)
        emp[fifa3] = dict(sum_e=E, n=len(rs),
                          vec=[sum(r["evidence"] * r["vec"][i] for r in rs) / E for i in range(k)])

    # 4. blend for all 48 WC2026 nations
    out = []
    for name, fifa3 in sorted(nat.items()):
        cf = conf[name]
        prior = confed_prior.get(cf) or global_prior
        prior_src = "confederation" if cf in confed_prior else "global"
        e = emp.get(fifa3)
        if e:
            lam = p.lambda_max * (1.0 - math.exp(-e["sum_e"] / p.tau))
            mix = [(1 - lam) * prior[i] + lam * e["vec"][i] for i in range(k)]
            out.append(dict(fifa3=fifa3, name=name, confed=cf, n=e["n"], sum_e=e["sum_e"],
                            lam=lam, prior_src=prior_src, prior=prior, emp=e["vec"], blend=mix))
        else:
            out.append(dict(fifa3=fifa3, name=name, confed=cf, n=0, sum_e=0.0, lam=0.0,
                            prior_src=prior_src, prior=prior, emp=None, blend=prior))
    return out


def report(out: list[dict]) -> None:
    out = sorted(out, key=lambda r: (r["confed"], r["name"]))
    print(f"\n{'nation':24} {'cf':9} {'n':>2} {'sumE':>5} {'lam':>5}  "
          f"{'  '.join(a[:5] for a in AXES)}   prior")
    for r in out:
        axs = "  ".join(f"{v:.3f}" for v in r["blend"])
        tag = "" if r["emp"] else "  <DARK pure-prior>"
        print(f"{r['name']:24} {r['confed']:9} {r['n']:>2} {r['sum_e']:>5.2f} "
              f"{r['lam']:>5.2f}  {axs}  {r['prior_src']}{tag}")
    dark = [r["name"] for r in out if not r["emp"]]
    print(f"\n{len(out)} nations  |  {len(out)-len(dark)} blended, {len(dark)} pure-prior: {dark}")


def apply(con, out: list[dict]) -> None:
    con.execute("CREATE OR REPLACE TABLE team_playstyle_blended ("
                "nation_fifa3 VARCHAR PRIMARY KEY, nation VARCHAR, confederation VARCHAR, "
                "n_tournament_rows INTEGER, sum_evidence DOUBLE, lambda_team DOUBLE, "
                "has_empirical BOOLEAN, prior_source VARCHAR, "
                + ", ".join(f"{a} DOUBLE" for a in AXES) + ", "
                + ", ".join(f"prior_{a} DOUBLE" for a in AXES) + ", "
                + ", ".join(f"emp_{a} DOUBLE" for a in AXES) + ", "
                "model_version VARCHAR, created_at TIMESTAMP DEFAULT now())")
    ncol = 8 + 3 * len(AXES) + 1
    for r in out:
        emp_vals = r["emp"] if r["emp"] else [None] * len(AXES)
        con.execute(
            "INSERT INTO team_playstyle_blended "
            "(nation_fifa3, nation, confederation, n_tournament_rows, sum_evidence, lambda_team, "
            "has_empirical, prior_source, " + ", ".join(AXES) + ", "
            + ", ".join(f"prior_{a}" for a in AXES) + ", "
            + ", ".join(f"emp_{a}" for a in AXES) + ", model_version) "
            "VALUES (" + ", ".join(["?"] * ncol) + ")",
            [r["fifa3"], r["name"], r["confed"], r["n"], r["sum_e"], r["lam"],
             r["emp"] is not None, r["prior_src"], *r["blend"], *r["prior"], *emp_vals, MODEL_VERSION])
    n = con.execute("SELECT COUNT(*) FROM team_playstyle_blended").fetchone()[0]
    print(f"\nAPPLIED: team_playstyle_blended = {n} rows")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    p = env_params()
    print(f"params: {p._asdict()}")
    con = duckdb.connect(str(DB), read_only=not args.apply)
    rows, cfgs = load_inputs(con)
    out = blend(rows, cfgs, p)
    report(out)
    if args.apply:
        apply(con, out)
    else:
        print("\n(dry-run; pass --apply to write team_playstyle_blended)")
    con.close()


if __name__ == "__main__":
    main()
