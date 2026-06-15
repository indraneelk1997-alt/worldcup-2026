#!/usr/bin/env python3
"""
dashboard/model_api.py -- thin adapter over the chessboard model (item 8,
src/load/v2_ingest/zone_aggregate.py) for the Streamlit dashboard.

Why this module exists (docs/dashboard_design.md S2):
  * Keeps the Streamlit view presentation-only -- every model call funnels
    through here, so the view never touches the model's private helpers.
  * Closes two gaps in the model's own helpers:
      - surfaces player NAMES (the model's _assemble_team drops them);
      - returns the {slot: ea_id} XI dict so the V2 player-swap can override a
        slot and reassemble.
  * Deliberately Streamlit-AGNOSTIC: no `import streamlit` here. That lets this
    run from the CLI (self-test below) and be reused by the later web-app port.
    The caching decorators (st.cache_resource / st.cache_data) live in app.py.

Self-test -- proves the whole contract against the real DB, no Streamlit:
  uv run python dashboard/model_api.py            # default ESP vs ENG
  uv run python dashboard/model_api.py BRA FRA
Compare the output against the model's own probe for the same pair:
  uv run python src/load/v2_ingest/zone_aggregate.py --scoreline ESP ENG
(They should agree -- this adapter only re-packages those same calls.)
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Two entries on sys.path, because the model's modules mix import styles:
#   * repo root      -> resolves the package-absolute `from src.load.v2_ingest...`
#   * the v2_ingest dir -> resolves the BARE sibling imports some probe modules
#     use (e.g. _probe_adjusted_ratings.py does `import _ea_attribute_buckets`).
# Running a model script directly puts its own dir on the path automatically, so
# those bare imports "just work" there; launched from dashboard/ they don't, so
# we add the dir explicitly to mirror the model's assumed execution context.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src" / "load" / "v2_ingest"))

# Default the dashboard to the trimmed runtime DB when it's present (friend
# parity: you run exactly what a friend with only the committed ~17 MB DB runs).
# An explicit WC2026_DB always wins; with no trimmed DB we fall back to the
# model's own default (the full local DB). This must run BEFORE the model import
# below, because zone_battle resolves DB_PATH from the env at import time.
if "WC2026_DB" not in os.environ:
    _dash = _ROOT / "data" / "processed" / "worldcup_dashboard.duckdb"
    if _dash.exists():
        os.environ["WC2026_DB"] = str(_dash)

from src.load.v2_ingest.zone_aggregate import (          # noqa: E402
    _scoreline_setup, autopick_xi, load_gk_score,
    _lambda_pair, bivariate_poisson_matrix, _matrix_summary,
)
from src.load.v2_ingest.formation_assembly import assemble, team_boards  # noqa: E402

DEFAULT_FORMATION = "4-3-3"


def setup(formation: str = DEFAULT_FORMATION):
    """Heavy one-time load. Returns (con, P): a read-only DuckDB handle + the
    config/derived-input bundle the model needs (scores, cfg, fwd, zxt, volume,
    ...). Expensive -- wrap in @st.cache_resource upstream (keyed by formation)."""
    return _scoreline_setup(formation)


def list_nations(con) -> list[str]:
    """FIFA-3 codes we can build a team for (the blended-playstyle universe).
    These are the dropdown options for the matchup pickers."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT nation_fifa3 FROM team_playstyle_blended ORDER BY 1"
    ).fetchall()]


def nation_names() -> dict[str, str]:
    """FIFA-3 code -> full nation name, inverted from data/config/nation_codes.json
    (which is stored name -> code). For pretty dropdown labels like 'Spain (ESP)'.
    Anything not in the file falls back to the bare code upstream."""
    raw = json.loads((_ROOT / "data" / "config" / "nation_codes.json")
                     .read_text(encoding="utf-8"))
    return {code: name for name, code in raw.items() if not name.startswith("_")}


def assemble_team(con, nation: str, P: dict, formation: str = DEFAULT_FORMATION):
    """Auto-pick the best XI -> full team bundle for the dashboard.

    Richer than the model's _assemble_team: also keeps the player NAMES and the
    {slot: ea_id} XI dict (both needed by the view / the V2 swap path). Keeps the
    `gk` (score) and `boards` keys exactly as the model's downstream functions
    (_lambda_pair / compute_attack_index) expect them, so this dict is a valid
    input to those.  Returns None if the squad can't be assembled.

      -> {nation, formation, sid, names, xi_ea, boards, gk, gk_name}
    """
    xi_ea, sid, names = autopick_xi(con, nation, formation, P["scores"])
    if not sid:
        return None
    _, slots = assemble(con, formation, nation, P["cfg"], P["fwd"], xi=xi_ea)
    gk_score, gk_name = load_gk_score(con, nation)
    return {"nation": nation, "formation": formation, "sid": sid, "names": names,
            "xi_ea": xi_ea, "boards": team_boards(slots),
            "gk": gk_score, "gk_name": gk_name}


def matchup(con, nation_a: str, nation_b: str, P: dict,
            formation: str = DEFAULT_FORMATION, l3: float = 0.0) -> dict:
    """Full A-vs-B result for the dashboard: assemble both XIs -> lambda-means
    -> bivariate-Poisson scoreline matrix + W/D/L summary.

    Rows of `matrix` = team_a goals, cols = team_b goals (so summary['p_home']
    is team_a's win prob). Raises ValueError if either side can't be assembled.

      -> {team_a, team_b, lam_a, lam_b, matrix, summary}
    """
    ta = assemble_team(con, nation_a, P, formation)
    tb = assemble_team(con, nation_b, P, formation)
    if ta is None or tb is None:
        raise ValueError(f"could not assemble {nation_a if ta is None else nation_b}")
    lam_a, lam_b = _lambda_pair(con, ta, tb, P)
    l1, l2 = max(lam_a - l3, 0.0), max(lam_b - l3, 0.0)
    M = bivariate_poisson_matrix(l1, l2, l3)
    return {"team_a": ta, "team_b": tb, "lam_a": lam_a, "lam_b": lam_b,
            "matrix": M, "summary": _matrix_summary(M)}


# --------------------------------------------------------------------------- #
# CLI self-test (no Streamlit) -- mirrors zone_aggregate.py --scoreline output.
# --------------------------------------------------------------------------- #
def _gk_str(team: dict) -> str:
    return f"{team['gk_name']} ({team['gk']:.0f})" if team.get("gk") else "none"


def _selftest(a: str = "ESP", b: str = "ENG") -> None:
    con, P = setup()
    try:
        print(f"nations available: {len(list_nations(con))}")
        r = matchup(con, a, b, P)
    finally:
        con.close()
    ta, tb, s = r["team_a"], r["team_b"], r["summary"]
    print(f"\n{a} XI: " + ", ".join(ta["names"][k] for k in sorted(ta["names"])))
    print(f"   +GK {_gk_str(ta)}")
    print(f"{b} XI: " + ", ".join(tb["names"][k] for k in sorted(tb["names"])))
    print(f"   +GK {_gk_str(tb)}")
    print(f"\nlambda-mean:  {a} {r['lam_a']:.3f}   {b} {r['lam_b']:.3f}")
    print(f"P(win) {a} {s['p_home']*100:.1f}% | draw {s['p_draw']*100:.1f}% | "
          f"{b} {s['p_away']*100:.1f}%")
    print(f"most-likely {s['ml_score'][0]}-{s['ml_score'][1]} (p={s['ml_p']*100:.1f}%)"
          f"   E[goals] {s['eg_home']:.2f}-{s['eg_away']:.2f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    _selftest(*(a[:2] if len(a) >= 2 else ()))
