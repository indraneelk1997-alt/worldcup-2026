#!/usr/bin/env python3
"""
dashboard/app.py -- WC2026 Match Simulator, Streamlit V1 (vertical pitch).

V1 (docs/dashboard_design.md S3): a VERTICAL formation pitch, one team at a time,
oriented like a real match -- Team A home at the bottom attacking up, Team B home
at the top attacking down. Sidebar holds the controls (team A/B, which team's
pitch, the 4 view modes). Beside the pitch: a team-stats panel (player attributes
/ tunables / substitutes come in V2). Below the pitch: a deterministic strategy
write-up. Scoreline matrix is a blue heatmap.

All model calls go through model_api (the Streamlit-agnostic adapter).

Run:
  uv run streamlit run dashboard/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                       # noqa: E402
import pandas as pd                      # noqa: E402
import plotly.graph_objects as go        # noqa: E402
import streamlit as st                   # noqa: E402

import model_api as api                  # noqa: E402

FORMATION = "4-3-3"      # V0/V1 fixed; formation knob lands in V2
GRID = 6                 # scoreline matrix shown for 0..GRID goals each side

FILL = {"GK": "#fde68a", "DEF": "#bfdbfe", "MID": "#fed7aa", "FWD": "#fecaca"}
EDGE = {"GK": "#ca8a04", "DEF": "#2563eb", "MID": "#ea580c", "FWD": "#dc2626"}
INK = "#0f172a"
PITCH = "#9ccc9c"

VIEW_LABELS = {"standard": "Standard formation", "possession": "Possession-balanced",
               "attack": "Attack profile", "defense": "Defense profile"}
AXIS_LABELS = [("possession", "Possession"), ("line_height", "Line height"),
               ("ppda", "Pressing"), ("width", "Width"), ("directness", "Directness")]


# --- cached model access ---------------------------------------------------- #
@st.cache_resource
def get_setup(formation: str):
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
    """Cached on the hashable args; _con/_P are skipped (underscore prefix)."""
    return api.matchup(_con, nation_a, nation_b, _P, formation)


# --- vertical pitch rendering ----------------------------------------------- #
# Portrait pitch: width = PITCH_WID (x, 80), length = PITCH_LEN (y, 120).
def _vmap(band: float, lane: float, up: bool) -> tuple[float, float]:
    """(band, lane) -> screen (x, y) for a vertical pitch. `up`=team attacks up
    (home at bottom); else attacks down (home at top) with L/R mirrored so each
    player's own left/right stays correct."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    if up:
        x = (lane + 0.5) / api.N_LANES * W
        y = (band + 0.5) / api.N_BANDS * L
    else:
        x = (api.N_LANES - lane - 0.5) / api.N_LANES * W
        y = L - (band + 0.5) / api.N_BANDS * L
    return x, y


def _pitch_lines_v():
    """None-separated polyline for vertical pitch markings."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    xs: list = []
    ys: list = []

    def rect(x0, y0, x1, y1):
        xs.extend([x0, x1, x1, x0, x0, None])
        ys.extend([y0, y0, y1, y1, y0, None])

    rect(0, 0, W, L)                                   # outline
    xs.extend([0, W, None]); ys.extend([L / 2, L / 2, None])   # halfway line
    th = np.linspace(0, 2 * np.pi, 50)                 # centre circle
    xs.extend(list(W / 2 + 10 * np.cos(th)) + [None])
    ys.extend(list(L / 2 + 10 * np.sin(th)) + [None])
    rect(W / 2 - 22, 0, W / 2 + 22, 18)                # penalty boxes
    rect(W / 2 - 22, L - 18, W / 2 + 22, L)
    rect(W / 2 - 10, 0, W / 2 + 10, 6)                 # six-yard boxes
    rect(W / 2 - 10, L - 6, W / 2 + 10, L)
    return xs, ys


def _token_label(t: dict) -> str:
    sn = t["name"].split()[-1] if t.get("name") else ""
    return f"{sn} {t['ovr']}" if t.get("ovr") else sn


def draw_pitch(team: dict, view: str, up: bool, title: str) -> go.Figure:
    W, L = api.PITCH_WID, api.PITCH_LEN
    layout = api.pitch_layout(team, view)
    hm = api.team_heatmap(team, view)
    x_centers = [_vmap(0, l, up)[0] for l in range(api.N_LANES)]
    y_centers = [_vmap(b, 0, up)[1] for b in range(api.N_BANDS)]

    fig = go.Figure()
    # 1. occupancy heatmap (z[band, lane]; x=lane centres, y=band centres oriented)
    fig.add_trace(go.Heatmap(
        x=x_centers, y=y_centers, z=hm, zmin=0.0, zsmooth="best", showscale=False,
        hoverinfo="skip",
        colorscale=[[0.0, "rgba(255,255,255,0)"], [0.25, "rgba(255,237,160,0.45)"],
                    [0.55, "rgba(254,178,76,0.70)"], [1.0, "rgba(240,59,32,0.85)"]]))
    # 2. markings
    lx, ly = _pitch_lines_v()
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines",
                             line=dict(color="white", width=2), hoverinfo="skip"))
    # 3. tokens
    pts = [_vmap(t["band"], t["lane"], up) for t in layout]
    fig.add_trace(go.Scatter(
        x=[p[0] for p in pts], y=[p[1] for p in pts], mode="markers+text",
        marker=dict(size=24, color=[FILL[t["group"]] for t in layout],
                    line=dict(width=2, color=[EDGE[t["group"]] for t in layout])),
        text=[t["position_code"] for t in layout], textposition="middle center",
        textfont=dict(size=9, color=INK),
        customdata=[[t.get("name") or "", t["position_code"], t.get("ovr") or 0]
                    for t in layout],
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]} · "
                      "EA %{customdata[2]}<extra></extra>"))
    # 4. surname + EA ovr below each token (lower y = visually below)
    fig.add_trace(go.Scatter(
        x=[p[0] for p in pts], y=[p[1] - 4.5 for p in pts], mode="text",
        text=[_token_label(t) for t in layout], textposition="middle center",
        textfont=dict(size=9, color=INK), hoverinfo="skip"))

    fig.update_xaxes(visible=False, range=[-6, W + 6])
    fig.update_yaxes(visible=False, range=[-6, L + 6], scaleanchor="x", scaleratio=1)
    fig.update_layout(
        plot_bgcolor=PITCH, paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=6, r=6, t=8, b=6), height=560, showlegend=False)
    return fig


# --- scoreline matrix (blue heatmap, matplotlib-free) ----------------------- #
def style_scoreline(M: np.ndarray, a: str, b: str):
    sub = M[:GRID + 1, :GRID + 1] * 100.0
    df = pd.DataFrame(sub, index=[str(i) for i in range(GRID + 1)],
                      columns=[str(j) for j in range(GRID + 1)])
    df.index.name = f"{a} \\ {b}"
    vmax = float(sub.max()) or 1.0

    def blue(v):
        a_ = 0.08 + 0.85 * (v / vmax)          # white text -> blue can go darker for pop
        return f"background-color: rgba(37, 99, 235, {a_:.3f}); color: white"

    return df.style.format("{:.1f}%").map(blue)


# --- info / strategy panels ------------------------------------------------- #
def render_panel(team: dict, view: str, name: str) -> None:
    st.subheader(name)
    gk = (f"{team['gk_name']} ({team['gk_ovr']})" if team.get("gk_ovr")
          else team.get("gk_name") or "—")
    st.markdown(f"Formation **{team['formation']}** · {VIEW_LABELS[view]} · **GK** {gk}")
    st.caption("Team playstyle (0–1 percentile vs the field)")
    ax = team["axes"]
    for key, label in AXIS_LABELS:
        v = min(max(float(ax.get(key, 0.0)), 0.0), 1.0)
        st.progress(v, text=f"{label} — {v:.2f}")


def render_strategy(team: dict, name: str) -> None:
    notes = api.strategy_notes(team)
    st.markdown(f"**Play style — {name}:** {notes['summary']}")
    st.markdown("✅ **Strengths:**  " + "  ·  ".join(notes["strengths"]))
    st.markdown("⚠️ **Watch-outs:**  " + "  ·  ".join(notes["weaknesses"]))


# --- app -------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="WC2026 Match Simulator", layout="wide")

    con, P = get_setup(FORMATION)
    nations = get_nations(FORMATION)
    labels = get_labels()

    def lbl(code: str) -> str:
        name = labels.get(code)
        return f"{name} ({code})" if name else code

    with st.sidebar:
        st.header("Match")
        a = st.selectbox("Team A (home, attacks up)", nations, format_func=lbl,
                         index=nations.index("ESP") if "ESP" in nations else 0)
        b = st.selectbox("Team B (away, attacks down)", nations, format_func=lbl,
                         index=nations.index("ENG") if "ENG" in nations else min(1, len(nations) - 1))
        st.divider()
        st.header("Pitch")
        side = st.radio("Show team", [a, b], format_func=lbl, disabled=(a == b))
        view = st.radio("View", list(api.VIEWS), index=list(api.VIEWS).index("possession"),
                        format_func=lambda v: VIEW_LABELS[v])

    st.title("⚽ WC2026 Match Simulator")
    if a == b:
        st.warning("Pick two different nations in the sidebar.")
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

    is_a = side == a
    team = r["team_a"] if is_a else r["team_b"]
    pcol, icol = st.columns([0.46, 0.54])
    with pcol:
        st.plotly_chart(
            draw_pitch(team, view, up=is_a, title=f"{lbl(side)} — {team['formation']}"),
            use_container_width=True)
    with icol:
        render_panel(team, view, lbl(side))

    # full-width strategy strip — uses the whole screen, not a narrow column
    render_strategy(team, lbl(side))
    st.caption("Player attributes · tunable knobs · substitutes — coming in V2.")

    with st.expander("Scoreline probability matrix", expanded=True):
        st.caption(f"Rows = {lbl(a)} goals · columns = {lbl(b)} goals · "
                   "darker blue = more likely.")
        st.dataframe(style_scoreline(r["matrix"], a, b), use_container_width=True)


if __name__ == "__main__":
    main()
