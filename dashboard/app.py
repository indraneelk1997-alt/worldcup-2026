#!/usr/bin/env python3
"""
dashboard/app.py -- WC2026 Match Simulator, Streamlit V0 (walking skeleton).

V0 scope (docs/dashboard_design.md S3): pick two nations -> see their auto-picked
XIs + the bivariate-Poisson scoreline (W/D/L, most-likely score, full matrix).
Formation is fixed at 4-3-3 for V0; the formation picker arrives with the V2
knobs. Every model call goes through model_api (the Streamlit-agnostic adapter);
this file stays presentation-only.

Run:
  uv run streamlit run dashboard/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# This script's own dir on sys.path so `import model_api` resolves however
# streamlit launches the file. (model_api itself adds the repo + v2_ingest dirs.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                       # noqa: E402
import pandas as pd                      # noqa: E402
import streamlit as st                   # noqa: E402

import model_api as api                  # noqa: E402

FORMATION = "4-3-3"      # V0 fixed; formation knob lands in V2
GRID = 6                 # show the scoreline matrix for 0..GRID goals each side


# --- cached model access ---------------------------------------------------- #
@st.cache_resource
def get_setup(formation: str):
    """Heavy one-time model load (DB handle + configs), cached app-wide."""
    return api.setup(formation)


@st.cache_data
def get_nations(formation: str) -> list[str]:
    con, _ = get_setup(formation)
    return api.list_nations(con)


@st.cache_data
def get_labels() -> dict[str, str]:
    return api.nation_names()


@st.cache_data
def get_matchup(_con, _P, nation_a: str, nation_b: str, formation: str):
    """Cached on the hashable args only; the leading underscores on _con/_P tell
    st.cache_data NOT to hash them (they're the live DB handle + config bundle)."""
    return api.matchup(_con, nation_a, nation_b, _P, formation)


# --- view helpers ----------------------------------------------------------- #
def xi_markdown(team: dict) -> str:
    names = [team["names"][k] for k in sorted(team["names"])]
    gk = f"{team['gk_name']} ({team['gk']:.0f})" if team.get("gk") else "—"
    body = "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))
    return f"**GK:** {gk}\n\n{body}"


def scoreline_df(M: np.ndarray, a: str, b: str) -> pd.DataFrame:
    sub = M[:GRID + 1, :GRID + 1] * 100.0
    df = pd.DataFrame(sub, index=[str(i) for i in range(GRID + 1)],
                      columns=[str(j) for j in range(GRID + 1)])
    df.index.name = f"{a} \\ {b}"
    return df


# --- app -------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="WC2026 Match Simulator", layout="wide")
    st.title("⚽ WC2026 Match Simulator")
    st.caption("Chessboard model · V0 walking skeleton — pick two nations, see the "
               "simulated scoreline. Formation fixed at 4-3-3 (knobs arrive in V2).")

    con, P = get_setup(FORMATION)
    nations = get_nations(FORMATION)
    labels = get_labels()

    def lbl(code: str) -> str:
        name = labels.get(code)
        return f"{name} ({code})" if name else code

    c1, c2 = st.columns(2)
    a = c1.selectbox("Team A", nations, format_func=lbl,
                     index=nations.index("ESP") if "ESP" in nations else 0)
    b = c2.selectbox("Team B", nations, format_func=lbl,
                     index=nations.index("ENG") if "ENG" in nations else min(1, len(nations) - 1))

    if a == b:
        st.warning("Pick two different nations.")
        return

    try:
        r = get_matchup(con, P, a, b, FORMATION)
    except ValueError as e:
        st.error(str(e))
        return

    s = r["summary"]
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{lbl(a)} win", f"{s['p_home'] * 100:.1f}%")
    m2.metric("Draw", f"{s['p_draw'] * 100:.1f}%")
    m3.metric(f"{lbl(b)} win", f"{s['p_away'] * 100:.1f}%")
    st.markdown(
        f"**Most likely:** {lbl(a)} {s['ml_score'][0]}–{s['ml_score'][1]} {lbl(b)} "
        f"(p={s['ml_p'] * 100:.1f}%)  ·  **E[goals]:** {s['eg_home']:.2f} – "
        f"{s['eg_away']:.2f}  ·  **λ-mean:** {r['lam_a']:.2f} / {r['lam_b']:.2f}")

    x1, x2 = st.columns(2)
    x1.subheader(f"{lbl(a)} XI")
    x1.markdown(xi_markdown(r["team_a"]))
    x2.subheader(f"{lbl(b)} XI")
    x2.markdown(xi_markdown(r["team_b"]))

    st.subheader("Scoreline probability (%)")
    st.caption(f"Rows = {lbl(a)} goals · columns = {lbl(b)} goals.")
    st.dataframe(scoreline_df(r["matrix"], a, b).style.format("{:.1f}"),
                 use_container_width=True)


if __name__ == "__main__":
    main()
