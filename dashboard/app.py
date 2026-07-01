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

DEFAULT_FORMATION = "4-3-3"   # setup default; per-team formation chosen in the panel
GRID = 6                 # scoreline matrix shown for 0..GRID goals each side

FILL = {"GK": "#fde68a", "DEF": "#bfdbfe", "MID": "#fed7aa", "FWD": "#fecaca"}
EDGE = {"GK": "#ca8a04", "DEF": "#2563eb", "MID": "#ea580c", "FWD": "#dc2626"}
INK = "#0f172a"
FADE_INK = "rgba(15,23,42,0.30)"          # dimmed token text when another is selected
PITCH = "#9ccc9c"
RADAR_A, RADAR_B = "#dc2626", "#2563eb"   # team A = red, team B = blue (V3 overlays)

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
def get_blend():
    """Canonical engine's blend frame (all outfield players). Cached: it's one
    all-player build, reused across the audit page's player picks."""
    con, _ = get_setup(DEFAULT_FORMATION)
    return api.blend_frame(con)


# Zone strengths are computed live from the SHOWN team (api.zone_strengths_for_team)
# so they reflect the exact XI on the pitch incl. player swaps — see main(). A
# single board sweep is cheap, like matchup.

# Matchup is computed live (not cached): it now depends on per-team formation +
# XI overrides, and a single assemble+scoreline is cheap. setup stays cached.


# --- vertical pitch rendering ----------------------------------------------- #
# Portrait pitch: width = PITCH_WID (x, 80), length = PITCH_LEN (y, 120).
def _vmap(band: float, lane: float, up: bool) -> tuple[float, float]:
    """(band, lane) -> screen (x, y) for a HORIZONTAL pitch (S46). Length
    (PITCH_LEN) is the horizontal x-axis, width (PITCH_WID) the vertical y-axis.
    `up`=team attacks left->right (own goal at the left); else right->left (own
    goal at the right) with the flank axis mirrored too, so Team B is a 180°
    rotation of Team A on the shared frame and each player's own L/R stays
    correct. Lane 0 (left flank) -> top for the L->R team."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    if up:
        x = (band + 0.5) / api.N_BANDS * L
        y = W - (lane + 0.5) / api.N_LANES * W
    else:
        x = L - (band + 0.5) / api.N_BANDS * L
        y = (lane + 0.5) / api.N_LANES * W
    return x, y


def _pitch_lines():
    """None-separated polyline for HORIZONTAL pitch markings (S46). L = length
    on the x-axis, W = width on the y-axis."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    xs: list = []
    ys: list = []

    def rect(x0, y0, x1, y1):
        xs.extend([x0, x1, x1, x0, x0, None])
        ys.extend([y0, y0, y1, y1, y0, None])

    rect(0, 0, L, W)                                   # outline
    xs.extend([L / 2, L / 2, None]); ys.extend([0, W, None])   # halfway line
    th = np.linspace(0, 2 * np.pi, 50)                 # centre circle
    xs.extend(list(L / 2 + 10 * np.cos(th)) + [None])
    ys.extend(list(W / 2 + 10 * np.sin(th)) + [None])
    rect(0, W / 2 - 22, 18, W / 2 + 22)                # penalty boxes (L / R)
    rect(L - 18, W / 2 - 22, L, W / 2 + 22)
    rect(0, W / 2 - 10, 6, W / 2 + 10)                 # six-yard boxes (L / R)
    rect(L - 6, W / 2 - 10, L, W / 2 + 10)
    return xs, ys


def _token_label(t: dict) -> str:
    sn = t["name"].split()[-1] if t.get("name") else ""
    return f"{sn} {t['ovr']}" if t.get("ovr") else sn


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgba(rgb: tuple[int, int, int], a: float) -> str:
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"


# Surface gradients (S46, gentler ramp): a near-linear alpha climb with extra
# low/mid stops so 0.1-0.5-of-max occupancy stays distinguishable (the first ramp
# crushed everything below the peak into near-transparency). warm = Team A, cool =
# Team B; each stop's base alpha is scaled by the heat-opacity slider.
_WARM = [(0.00, (245, 255, 235), 0.00), (0.10, (255, 240, 170), 0.20),
         (0.22, (255, 214, 110), 0.32), (0.36, (253, 184, 80), 0.44),
         (0.52, (250, 150, 60), 0.56), (0.70, (242, 108, 45), 0.68),
         (0.86, (228, 66, 38), 0.80), (1.00, (200, 34, 30), 0.90)]
_COOL = [(0.00, (235, 245, 255), 0.00), (0.10, (200, 228, 252), 0.20),
         (0.22, (150, 200, 245), 0.32), (0.36, (105, 170, 235), 0.44),
         (0.52, (66, 135, 220), 0.56), (0.70, (45, 95, 205), 0.68),
         (0.86, (35, 60, 175), 0.80), (1.00, (22, 30, 120), 0.90)]


def _colorscale(scheme: str, alpha: float):
    stops = _WARM if scheme == "warm" else _COOL
    return [[p, f"rgba({r},{g},{b},{ba * alpha:.3f})"] for p, (r, g, b), ba in stops]


def _add_surface(fig, team, view, up, scheme, alpha, gamma, kernel_slot=None,
                 grid_override=None, grid_raw=None) -> None:
    """One team's surface, own-max normalised + gamma-shaped (contrast), drawn with
    a long warm/cool gradient. `grid_override` (a 6×5 array, e.g. zone strengths)
    bypasses occupancy as a discrete map; `grid_raw` (e.g. a summed set of player
    kernels) takes the smooth own-max path; else a selected player shows their
    kernel, otherwise the team's occupancy surface for `view`."""
    if grid_override is not None:
        # Already 0-1 (min-max stretched upstream); nan = unoccupied -> stays nan
        # so the cell renders as transparent grass. Discrete cells (no smoothing)
        # so it reads as a per-zone map, not a flow field.
        z = np.power(grid_override, gamma)
        smooth = False
    else:
        grid = grid_raw
        if grid is None:
            grid = (api.player_kernel(team, kernel_slot, view)
                    if kernel_slot is not None else None)
        if grid is None:
            grid = api.team_heatmap(team, view)
        zmax = float(grid.max()) or 1.0
        z = (grid / zmax) ** gamma                    # contrast control
        smooth = "best"
    xs = [_vmap(b, 0, up)[0] for b in range(api.N_BANDS)]
    ys = [_vmap(0, l, up)[1] for l in range(api.N_LANES)]
    fig.add_trace(go.Heatmap(
        x=xs, y=ys, z=z.T, zmin=0.0, zmax=1.0, zsmooth=smooth,
        showscale=False, hoverinfo="skip", colorscale=_colorscale(scheme, alpha)))


def _sum_kernels(team, slots, view):
    """Sum the occupancy kernels of `slots` (a list of slot_no) for one team, in
    `view`. -> a 6×5 grid (or None if none had a kernel, e.g. all GK)."""
    g = None
    for s in slots:
        k = api.player_kernel(team, s, view)
        if k is not None:
            g = k.copy() if g is None else g + k
    return g


def _add_tokens(fig, layout, up, hi_slots, edge_rgb, global_sel,
                base_alpha, fade_alpha) -> int:
    """One team's token trace (markers + code) + a surname/ovr label trace. Returns
    the selectable marker trace's curve index. Team identity = marker EDGE colour;
    group = fill. Fade lives in the colour ALPHA (not marker.opacity) and the trace
    disables Plotly's own selection dimming, so there's ONE clean fade level —
    highlighted tokens (in `hi_slots`) full + enlarged, all others (both teams)
    dimmed to fade_alpha."""
    hi_slots = set(hi_slots or ())
    pts = [_vmap(t["band"], t["lane"], up) for t in layout]
    is_sel = [t["slot_no"] in hi_slots for t in layout]

    def a_for(s):
        return 1.0 if s else (fade_alpha if global_sel else base_alpha)

    fills = [_rgba(_hex_to_rgb(FILL[t["group"]]), a_for(s))
             for t, s in zip(layout, is_sel)]
    edges = [_rgba(edge_rgb, a_for(s)) for s in is_sel]
    m_size = [32 if s else 24 for s in is_sel]
    m_lw = [5 if s else 2 for s in is_sel]
    ink = [INK if (s or not global_sel) else FADE_INK for s in is_sel]
    fig.add_trace(go.Scatter(
        x=[p[0] for p in pts], y=[p[1] for p in pts], mode="markers+text",
        marker=dict(size=m_size, color=fills, line=dict(width=m_lw, color=edges)),
        unselected=dict(marker=dict(opacity=1.0)),    # we own the fade (colour alpha)
        text=[t["position_code"] for t in layout], textposition="middle center",
        textfont=dict(size=9, color=ink),
        customdata=[[t.get("name") or "", t["position_code"], t.get("ovr") or 0]
                    for t in layout],
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]} · "
                      "EA %{customdata[2]}<extra></extra>"))
    curve = len(fig.data) - 1
    fig.add_trace(go.Scatter(
        x=[p[0] for p in pts], y=[p[1] - 4.5 for p in pts], mode="text",
        text=[_token_label(t) for t in layout], textposition="middle center",
        textfont=dict(size=8, color=ink), hoverinfo="skip"))
    return curve


def _zone_lines():
    """Dotted polyline at the 6-band / 5-lane zone boundaries (our zone grid)."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    xs: list = []
    ys: list = []
    for b in range(1, api.N_BANDS):              # band boundaries -> vertical lines
        x = b / api.N_BANDS * L
        xs.extend([x, x, None]); ys.extend([0, W, None])
    for l in range(1, api.N_LANES):              # lane boundaries -> horizontal lines
        y = l / api.N_LANES * W
        xs.extend([0, L, None]); ys.extend([y, y, None])
    return xs, ys


# RGB defaults for the two team surfaces (match RADAR_A / RADAR_B).
_RGB_A, _RGB_B = (220, 38, 38), (37, 99, 235)


def _zone_rect(zone_id: int, up: bool):
    """Closed rectangle (xs, ys) tracing the selected zone's cell on the pitch, in
    the attacker's orientation (same physical patch either way)."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    band, lane = divmod(zone_id, api.N_LANES)
    if up:
        x0, x1 = band / api.N_BANDS * L, (band + 1) / api.N_BANDS * L
        y0, y1 = W - (lane + 1) / api.N_LANES * W, W - lane / api.N_LANES * W
    else:
        x0, x1 = L - (band + 1) / api.N_BANDS * L, L - band / api.N_BANDS * L
        y0, y1 = lane / api.N_LANES * W, (lane + 1) / api.N_LANES * W
    return [x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0]


def draw_pitch(team_a, team_b, view, *, side_a, side_b, show_a, show_b, show_heat,
               show_zones, battle=False, battle_swap=False, surface_side=None,
               sel_side=None, sel_slot=None, pitch_color=PITCH,
               rgb_a=_RGB_A, rgb_b=_RGB_B, surf_alpha=0.55, surf_gamma=1.0,
               base_alpha=0.9, fade_alpha=0.25,
               strength_grid=None, strength_scheme="warm", zone_hi=None,
               hi_zone=None):
    """Horizontal two-team pitch (S46). A attacks L->R, B R->L. Surfaces use warm
    (A) / cool (B) gradients; with a player selected, only THAT player's kernel is
    drawn (their team's scheme). Highlight is driven by (sel_side, sel_slot) from
    the picker — no fragile pitch-click. Returns the figure."""
    W, L = api.PITCH_WID, api.PITCH_LEN
    has_sel = sel_side is not None and sel_slot is not None
    surface_side = surface_side or side_a
    # In battle mode each team uses its own battle PHASE (A attacks, B defends, or
    # swapped) for BOTH its surface and its token placement — so they converge in
    # the contested zone instead of both sitting in the same phase. Otherwise both
    # use the sidebar `view` (the possession blend etc.).
    va = ("defense" if battle_swap else "attack") if battle else view
    vb = ("attack" if battle_swap else "defense") if battle else view
    fig = go.Figure()

    # 1. surface (under everything). Priority: ZONE-BATTLE highlight (selected
    #    zone's top-N players per team, own kernels, warm A / cool B) > zone
    #    strength > selected player's kernel > battle overlay > one team's
    #    occupancy. Both teams' TOKENS always show.
    if zone_hi:
        for grp in zone_hi.values():
            g = _sum_kernels(grp["team"], grp["slots"], grp["view"])
            if g is not None:
                _add_surface(fig, None, grp["view"], grp["up"], grp["scheme"],
                             surf_alpha, surf_gamma, grid_raw=g)
    elif strength_grid is not None:
        _add_surface(fig, None, None, surface_side == side_a, strength_scheme,
                     surf_alpha, surf_gamma, grid_override=strength_grid)
    elif show_heat:
        if has_sel:
            if sel_side == side_a and show_a:
                _add_surface(fig, team_a, va, True, "warm", surf_alpha, surf_gamma, sel_slot)
            elif sel_side == side_b and show_b:
                _add_surface(fig, team_b, vb, False, "cool", surf_alpha, surf_gamma, sel_slot)
        elif battle:
            if show_a:
                _add_surface(fig, team_a, va, True, "warm", surf_alpha, surf_gamma)
            if show_b:
                _add_surface(fig, team_b, vb, False, "cool", surf_alpha, surf_gamma)
        elif surface_side == side_a and show_a:
            _add_surface(fig, team_a, va, True, "warm", surf_alpha, surf_gamma)
        elif surface_side == side_b and show_b:
            _add_surface(fig, team_b, vb, False, "cool", surf_alpha, surf_gamma)

    # 2. pitch markings
    lx, ly = _pitch_lines()
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines",
                             line=dict(color="white", width=2), hoverinfo="skip"))

    # 3. zone grid (dotted) — uniform 6 (length) x 5 (width) model grid
    if show_zones:
        zx, zy = _zone_lines()
        fig.add_trace(go.Scatter(
            x=zx, y=zy, mode="lines", hoverinfo="skip",
            line=dict(color="rgba(255,255,255,0.5)", width=1, dash="dot")))

    # 3b. selected zone border (bright outline of the inspected cell)
    if hi_zone is not None:
        zid, zup = hi_zone
        zrx, zry = _zone_rect(zid, zup)
        fig.add_trace(go.Scatter(x=zrx, y=zry, mode="lines", hoverinfo="skip",
                                 line=dict(color="#facc15", width=3)))

    # 4. tokens per shown team (each at its own battle phase va/vb so the two
    #    teams aren't both in the same phase). Highlighted = player pick + the
    #    zone-battle top-N for that side.
    zone_slots, zone_view = {}, {}
    if zone_hi:
        for grp in zone_hi.values():
            zone_slots.setdefault(grp["side"], set()).update(
                s for s in grp["slots"] if s is not None)
            zone_view[grp["side"]] = grp["view"]   # attacker->attack, defender->defense
    global_sel = has_sel or bool(zone_hi)
    for team, up, side, edge, tview in ((team_a, True, side_a, rgb_a, va),
                                        (team_b, False, side_b, rgb_b, vb)):
        if not (show_a if side == side_a else show_b):
            continue
        hi = set(zone_slots.get(side, set()))
        if has_sel and sel_side == side:
            hi.add(sel_slot)
        # In zone-battle mode place tokens by attack/defence phase (attacker=attack,
        # defender=defence), independent of the sidebar view — so positions match
        # the kernels and the contest.
        tv = zone_view.get(side, tview)
        layout = api.pitch_layout(team, tv)
        _add_tokens(fig, layout, up, hi, edge, global_sel, base_alpha, fade_alpha)

    fig.update_xaxes(visible=False, range=[-6, L + 6])
    fig.update_yaxes(visible=False, range=[-6, W + 6], scaleanchor="x", scaleratio=1)
    fig.update_layout(plot_bgcolor=pitch_color, paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=6, r=6, t=8, b=6), height=460, showlegend=False)
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


# --- playstyle radar (both teams overlaid; V3) ------------------------------ #
def radar_chart(team_a: dict, team_b: dict, name_a: str, name_b: str) -> go.Figure:
    """5-axis playstyle radar overlaying both teams (red A / blue B). Pure
    re-render of team['axes'] (0–1 percentiles) — replaces the V2 progress bars."""
    keys = [k for k, _ in AXIS_LABELS]
    cats = [lab for _, lab in AXIS_LABELS]

    def vals(team: dict) -> list[float]:
        return [min(max(float(team["axes"].get(k, 0.0)), 0.0), 1.0) for k in keys]

    va, vb = vals(team_a), vals(team_b)
    theta = cats + [cats[0]]                       # close the polygon
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=va + [va[0]], theta=theta, fill="toself", name=name_a,
        line=dict(color=RADAR_A), fillcolor="rgba(220,38,38,0.22)",
        hovertemplate="%{theta}: %{r:.2f}<extra>" + name_a + "</extra>"))
    fig.add_trace(go.Scatterpolar(
        r=vb + [vb[0]], theta=theta, fill="toself", name=name_b,
        line=dict(color=RADAR_B), fillcolor="rgba(37,99,235,0.22)",
        hovertemplate="%{theta}: %{r:.2f}<extra>" + name_b + "</extra>"))

    # Per-vertex value labels, coloured per team. On each axis the higher team's
    # label sits just OUTSIDE its vertex, the lower one just INSIDE — so the two
    # never collide (and they split even when equal: A out, B in).
    OFF = 0.07

    def _lab_r(mine: list[float], other: list[float], higher_out: bool) -> list[float]:
        out = []
        for m, o in zip(mine, other):
            outward = (m >= o) if higher_out else (m > o)
            out.append(min(max(m + (OFF if outward else -OFF), 0.05), 1.0))
        return out

    fig.add_trace(go.Scatterpolar(
        r=_lab_r(va, vb, True), theta=cats, mode="text",
        text=[f"{v:.2f}" for v in va], textfont=dict(color=RADAR_A, size=10),
        showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatterpolar(
        r=_lab_r(vb, va, False), theta=cats, mode="text",
        text=[f"{v:.2f}" for v in vb], textfont=dict(color=RADAR_B, size=10),
        showlegend=False, hoverinfo="skip"))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1],
                                   tickvals=[0.25, 0.5, 0.75, 1.0],
                                   showticklabels=False)),   # values now on the vertices
        showlegend=True, height=340, margin=dict(l=40, r=40, t=20, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.18, x=0.5, xanchor="center"),
        paper_bgcolor="rgba(0,0,0,0)")
    return fig


# --- info / strategy panels ------------------------------------------------- #
def _render_swaps(con, team: dict, nation: str, P: dict) -> None:
    """Substitute one starter for an eligible alternative (item 9). Eligible =
    can actually play that slot's position; ranked best-fit first."""
    pcs = {s["slot_no"]: s["position_code"] for s in team["slots"]}
    with st.expander("Substitutes / swap a player"):
        slot_no = st.selectbox(
            "Position", sorted(team["names"]), key=f"swslot_{nation}",
            format_func=lambda sn: f"{pcs.get(sn, '?')} · {team['names'][sn]}")
        alts = api.alternatives(con, nation, team["formation"], slot_no, P,
                                tuple(team["xi_ea"].values()))
        if not alts:
            st.caption("No eligible alternatives for this position.")
        else:
            pick = st.selectbox(
                "Replace with", alts, key=f"swpick_{nation}",
                format_func=lambda a: f"{a[2]} — fit {a[4]:.2f}")
            c1, c2 = st.columns(2)
            if c1.button("Swap in", key=f"swdo_{nation}", use_container_width=True):
                st.session_state.setdefault("ov", {}).setdefault(
                    nation, {})[slot_no] = pick[0]
                st.rerun()
            if c2.button("Reset XI", key=f"swrst_{nation}", use_container_width=True):
                st.session_state.get("ov", {}).pop(nation, None)
                st.rerun()


def _render_player(tok: dict, prof: dict | None) -> None:
    """Player tab body: identity, EA face stats, empirical positions, EA
    playstyles, and the adjusted-rating attributes (top-5 default, 5-at-a-time
    multiselect). V3 step 4."""
    st.subheader(tok.get("name") or "—")
    ovr = tok.get("ovr")
    sub = f"{tok['position_code']} · {tok['group']}"
    if prof and prof.get("ea_position"):
        sub += f" · EA {prof['ea_position']}"
        if prof.get("alt_positions"):
            sub += f" ({prof['alt_positions']})"
    if prof and prof.get("club"):
        sub += f" · {prof['club']}"
    st.caption(sub)

    if not prof:
        st.info("No detailed profile for this player (likely the GK or an "
                "unrated player).")
        return

    cov = prof.get("coverage")
    c1, c2 = st.columns([0.42, 0.58])
    c1.metric("EA overall (raw)", ovr or prof.get("overall") or "—",
              help="EA's own position-weighted overall — the RAW EA rating, not "
                   "empirically adjusted. The empirical effect is the per-phase "
                   "line below; ratings adjust per attribute, not as one overall.")
    with c2:
        st.caption("Data coverage")
        if cov:
            lab, hexc = api.COVERAGE_TIERS.get(cov["tier"], (cov["tier"], "#9ca3af"))
            st.markdown(
                f"<span style='background:{hexc};color:#fff;padding:3px 10px;"
                f"border-radius:8px;font-size:0.9rem'>{lab}</span>",
                unsafe_allow_html=True)
        else:
            st.markdown("—")

    # What the empirical data actually did: the per-phase shift (uniform within a
    # bucket). Replaces the misleading single 'Adj rating' scalar (S45 finding —
    # a flat mean over discriminators flattened specialists like Yamal).
    shifts = {}
    for a in prof["attrs"]:
        s = a["shift_s"] or 0.0
        if abs(s) > 1e-9:
            shifts[a["bucket"]] = s
    if shifts:
        parts = [f"{b} {'+' if s > 0 else ''}{s:.1f}"
                 for b, s in sorted(shifts.items(), key=lambda x: -x[1])]
        st.caption("**Empirical adjustment** vs EA raw, by phase:  "
                   + "  ·  ".join(parts) + "   · other phases unchanged")
    else:
        st.caption("**Empirical adjustment:** none applied (EA-only or unrated).")

    # Mean ADJUSTED rating per bucket (our buckets, not EA's face stats) — adjusted
    # where the empirical blend shifted the attribute, else the raw EA value.
    if prof["attrs"]:
        bvals: dict[str, list[float]] = {}
        for a in prof["attrs"]:
            if a["adj"] is not None:
                bvals.setdefault(a["bucket"], []).append(a["adj"])
        order = [("Attack", "ATT"), ("Defense", "DEF"), ("Possession", "POS"),
                 ("Skills", "SKL"), ("IQ", "IQ"), ("Physical", "PHY")]
        st.caption("Adjusted rating by bucket (mean of the bucket's attributes)")
        for col, (bk, lab) in zip(st.columns(6), order):
            vs = bvals.get(bk, [])
            col.metric(lab, f"{sum(vs) / len(vs):.0f}" if vs else "—")

    if cov and (cov["empirical_minutes_total"] or 0) > 0:
        st.caption(
            "Backed by club + international match data. A clean per-competition "
            "breakdown (League / Continental / International — matches & seasons, "
            "de-duplicated across data sources) comes with the ratings-audit view.")
    elif cov:
        st.caption("No empirical match data (EA-only or unrated).")

    if prof["positions"]:
        st.markdown("**Positions (empirical)**")
        bits = []
        for p in prof["positions"][:5]:
            share = (p["share"] or 0) * 100
            mark = "★" if p["is_modal"] else ("✓" if p["eligible"] else "")
            bits.append(f"{p['role']} {share:.0f}%{(' ' + mark) if mark else ''}")
        st.caption("  ·  ".join(bits) + "   (★ modal · ✓ eligible)")

    if prof["playstyles"]:
        st.markdown("**Playstyles (EA)**")
        sym = {"plus": " +", "plus_plus": " ++"}
        st.caption("  ·  ".join(f"{ps['playstyle']}{sym.get(ps['tier'], '')}"
                                for ps in prof["playstyles"]))

    attrs = prof["attrs"]
    if attrs:
        st.markdown("**Adjusted ratings**  ")
        names = [a["attribute"] for a in attrs]              # already adj-desc
        pick = st.multiselect(
            "Attributes (top 5 by default · max 5)", names, default=names[:5],
            max_selections=5, key=f"attrs_{tok['slot_no']}")
        by = {a["attribute"]: a for a in attrs}
        for nm in (pick or names[:5]):
            a = by[nm]
            adj, raw, sh = a["adj"], a["ea_raw"], a["shift_s"] or 0.0
            v = min(max((adj or 0) / 100.0, 0.0), 1.0)
            delta = f"  ·  raw {raw:.0f} → {adj:.0f}" if abs(sh) > 1e-9 else ""
            st.progress(v, text=f"{nm.replace('_', ' ')} — {adj:.0f}{delta}")
        st.caption("Values are EA-adjusted where empirical data shifted them, "
                   "else the raw EA rating.")


def _zone_list(rows: list[dict]) -> str:
    """One-line 'key (band) score' summary for a top/bottom zone list."""
    return "  ·  ".join(f"{r['key']} (B{r['band']}) — {r['score']:.0f}" for r in rows)


def render_zone_battle(d: dict, n_att: str, n_def: str) -> None:
    """Zone battle inspector body (8b) from a precomputed detail dict: four headline
    numbers (each side's occ-weighted attribute-score sum, P(attacker prevails),
    overall zone value) + per-team players (desc by occ) with playstyles and the
    occ-weighted per-attribute Approach/Main scores."""
    z, v = d["zone"], d["value"]
    st.caption(f"**B{z['band']}·L{z['lane']}** · {z['key']} · {z['context']}")
    m = st.columns(4)
    m[0].metric(f"{n_att} (att)", f"{d['att_score']['main']:.0f}",
                help="Occ-weighted attribute-score sum · approach "
                     f"{d['att_score']['approach']:.0f} / main "
                     f"{d['att_score']['main']:.0f}")
    m[1].metric(f"{n_def} (def)", f"{d['def_score']['main']:.0f}",
                help=f"approach {d['def_score']['approach']:.0f} / main "
                     f"{d['def_score']['main']:.0f}")
    m[2].metric(f"P({n_att} prevails)", f"{d['threat'] * 100:.0f}%")
    m[3].metric("Zone value ×10³", f"{v['zone_value'] * 1000:.2f}",
                help=f"entry {v['entry_share']:.3f} × Pwin {v['p_win']:.3f} × "
                     f"zone_xT {v['zone_xt']:.4f} × conv {v['conv_factor']:.3f} "
                     f"(shot_share {v['shot_share']:.2f})")
    for col, side, name in zip(st.columns(2), ("attacker", "defender"),
                               (n_att, n_def)):
        det = d[side]
        with col:
            st.markdown(f"**{name}** — by occupancy")
            for p in det["players"][:6]:
                ps = (" · _" + ", ".join(p["playstyles"]) + "_") if p["playstyles"] else ""
                st.markdown(f"`{p['occ']:.2f}`  {p['name']}{ps}")
            for stage in ("approach", "main"):
                if det[stage]:
                    attrs = "  ".join(f"{x['attr']} **{x['score']:.0f}**"
                                      for x in det[stage])
                    st.markdown(f"*{stage.capitalize()}* — {attrs}")


def render_panel(con, team: dict, view: str, name: str, nation: str,
                 fmts: list[str], auto_fmt: str, P: dict,
                 team_a: dict, team_b: dict, name_a: str, name_b: str,
                 sel_tok: dict | None = None, profile: dict | None = None,
                 zs: dict | None = None, zb_detail: dict | None = None,
                 n_att: str | None = None, n_def: str | None = None,
                 matrix=None, code_a: str | None = None,
                 code_b: str | None = None) -> None:
    """Info panel (V3, 8c) — four tabs: Team Stats (2-col formation+subs+strategy |
    radar, then zone-strength lists), Player Stats, Zone battle (the A-vs-B
    breakdown; its zone CONTROLS live above the pitch and drive the on-pitch
    highlight), and Probability matrix (the scoreline heatmap)."""
    tab_team, tab_player, tab_zone, tab_prob = st.tabs(
        ["Team Stats", "Player Stats", "Zone battle", "Probability matrix"])

    with tab_team:
        st.subheader(name)
        left, right = st.columns(2)
        with left:
            st.selectbox("Formation", fmts, key=f"fmt_{nation}",
                         help="Defaults to the auto best-fit shape; change it to "
                              "re-pick this squad's XI for a different formation.")
            gk = (f"{team['gk_name']} ({team['gk_ovr']})" if team.get("gk_ovr")
                  else team.get("gk_name") or "—")
            auto = " · auto best-fit" if team["formation"] == auto_fmt else ""
            st.caption(f"{VIEW_LABELS[view]} · GK {gk}{auto}")
            _render_swaps(con, team, nation, P)
            render_strategy(team, name)
        with right:
            st.caption("Playstyle (0–1 percentile vs the field) — both teams "
                       "overlaid (red / blue)")
            st.plotly_chart(radar_chart(team_a, team_b, name_a, name_b),
                            use_container_width=True)
        st.divider()
        st.caption("**Zone strengths** — mean adjusted rating of the players who "
                   "occupy each zone (≈75–90; higher = stronger occupants). "
                   "Team-intrinsic; toggle the surface on the pitch.")
        if not zs:
            st.info("Zone strengths unavailable (squad could not be assembled).")
        else:
            zc1, zc2 = st.columns(2)
            with zc1:
                st.markdown("**Attack — strongest** · " + _zone_list(zs["attack_top"]))
                st.markdown("**Attack — weakest** · " + _zone_list(zs["attack_bottom"]))
            with zc2:
                st.markdown("**Defence — strongest** · " + _zone_list(zs["defence_top"]))
                st.markdown("**Defence — weakest** · " + _zone_list(zs["defence_bottom"]))
            st.caption("Weakest ranks only zones the side actually occupies.")

    with tab_player:
        if sel_tok is None:
            st.caption("Highlight a player (picker above the pitch) to see their "
                       "profile — positions, playstyles, adjusted ratings.")
        else:
            _render_player(sel_tok, profile)

    with tab_zone:
        if zb_detail is None:
            st.caption("Pick a zone in the **Zone battle** dropdown above the pitch "
                       "(default *— none —*) to inspect that cell's A-vs-B contest.")
        else:
            st.caption(f"{n_att} attack vs {n_def} defence — pick the zone above "
                       "the pitch (the outlined cell).")
            render_zone_battle(zb_detail, n_att, n_def)

    with tab_prob:
        if matrix is not None:
            st.caption(f"Rows = {name_a} goals · columns = {name_b} goals · "
                       "darker blue = more likely.")
            st.dataframe(style_scoreline(matrix, code_a, code_b),
                         use_container_width=True)


def render_strategy(team: dict, name: str) -> None:
    notes = api.strategy_notes(team)
    st.markdown(f"**Play style — {name}:** {notes['summary']}")
    st.markdown("✅ **Strengths:**  " + "  ·  ".join(notes["strengths"]))
    st.markdown("⚠️ **Watch-outs:**  " + "  ·  ".join(notes["weaknesses"]))


# --- squad coverage page ---------------------------------------------------- #
TIER_LABEL_HEX = {lab: hx for lab, hx in api.COVERAGE_TIERS.values()}


def _mm(mins: int, mats: int) -> str:
    """minutes (matches), or an em-dash when there's nothing."""
    return f"{mins:,} ({mats})" if mins else "—"


def style_coverage(df: pd.DataFrame):
    """Tint the Tier cell by its tier colour (matplotlib-free Styler, same
    pattern as style_scoreline)."""
    def tint(lab):
        return f"background-color: {TIER_LABEL_HEX.get(lab, '#9ca3af')}; color: white"
    return df.style.map(tint, subset=["Tier"])


def render_coverage_page(con, nations, lbl) -> None:
    st.title("📊 Squad data coverage")
    nation = st.selectbox("Nation", nations, format_func=lbl,
                          index=nations.index("BRA") if "BRA" in nations else 0)
    rt = api.coverage_rating(con, nation)
    c1, c2, c3 = st.columns(3)
    c1.metric("Model-ready (outfield)", f"{rt['pct_ready']:.0f}%")
    c2.metric("Weighted coverage", f"{rt['weighted']:.0f}/100")
    c3.metric("Squad", f"{rt['n_squad']} ({rt['n_outfield']} outfield)")
    st.caption("Tier = the best data we hold per player. Green = model-ready "
               "(rateable); orange = real match data but EA-unmatched (a fixable "
               "linkage gap); red = coarse fallback; grey = goalkeeper (rated "
               "separately). Source cells show minutes (matches).")
    rows = api.coverage_rows(con, nation)
    disp = pd.DataFrame([{
        "Pos": r["grp"], "Player": r["player_name"],
        "Tier": api.COVERAGE_TIERS.get(r["coverage_tier"], (r["coverage_tier"],))[0],
        "Understat": _mm(r["understat_minutes"], r["understat_matches"]),
        "FBref": _mm(r["fbref_minutes"], r["fbref_matches"]),
        "StatsBomb": _mm(r["statsbomb_minutes"], r["statsbomb_matches"]),
        "EA": "✓" if r["has_ea"] else "—",
        "Adj": "✓" if r["has_adjusted"] else "—",
        "Caps": r["caps"] or 0,
    } for r in rows])
    st.dataframe(style_coverage(disp), use_container_width=True,
                 hide_index=True, height=560)


# --- ratings-audit page (V3 step 4b) ---------------------------------------- #
def _fmt_pct(v) -> str:
    return "—" if v is None else f"{v:.0f}"


def render_audit_page(con, nations, lbl) -> None:
    st.title("🔬 Ratings audit")
    st.caption(
        "How each player's EA rating is blended toward empirical performance.  "
        "blended pct = (1−λ)·EA pct + λ·empirical pct (percentiles within position "
        "group);  λ = min(minutes/900, 1)·CAP, CAP = Attack 0.60 / Possession 0.50 "
        "/ Defense 0.25, and 0 for off-role phases.  A positive Δ means empirical "
        "data raised the player; each attribute's shift follows from its phase Δ.")

    df = get_blend()
    nation = st.selectbox("Nation", nations, format_func=lbl,
                          index=nations.index("ESP") if "ESP" in nations else 0)
    players = con.execute(
        "SELECT squad_row_id, player_name, ea_id FROM wc2026_squad "
        "WHERE nation_code=? AND primary_position_group <> 'GK' "
        "ORDER BY player_name", [nation]).fetchall()
    if not players:
        st.info("No outfield players for this nation.")
        return
    pick = st.selectbox("Player", players, format_func=lambda p: p[1],
                        key=f"audit_pl_{nation}")
    srid, pname, ea_id = pick
    st.subheader(pname)

    pb = api.player_blend(df, srid)
    if pb is None:
        st.info("No blend record for this player (GK, or no empirical/EA link — "
                "their attributes stay at the raw EA prior).")
    else:
        st.caption(f"Position group: **{pb['grp']}**")
        rows = [{
            "Phase": d["dim"],
            "On-role": "✓" if d["on_role"] else "—",
            "Minutes": "—" if d["minutes"] is None else f"{d['minutes']:,.0f}",
            "EA pct": _fmt_pct(d["ea_pct"]),
            "Empirical pct": _fmt_pct(d["emp_pct"]),
            "λ": "—" if d["lam"] is None else f"{d['lam']:.2f}",
            "Blended pct": _fmt_pct(d["blended_pct"]),
            "Δ pct": "—" if d["delta_pct"] is None else f"{d['delta_pct']:+.0f}",
        } for d in pb["dims"]]
        st.markdown("**Per-phase blend** — the inputs to every attribute shift")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        bits = []
        for d in pb["dims"]:
            if d["empirical_value"] is not None:
                unit = "(g+xa)/90" if d["dim"] == "Attack" else "(kp+xgB+xgC)/90"
                bits.append(f"{d['dim']} {d['empirical_value']:.2f} {unit}")
        if pb["padj"] is not None:
            bits.append(f"Defense padj {pb['padj']:.1f} · suppression {pb['supp']:.1f}")
        if bits:
            st.caption("Empirical inputs:  " + "  ·  ".join(bits))

    prof = api.player_profile(con, srid, ea_id)
    if prof["attrs"]:
        st.markdown("**Attributes — EA raw → adjusted**")
        arows = [{
            "Attribute": a["attribute"].replace("_", " "),
            "Bucket": a["bucket"],
            "Disc.": "✓" if a["is_discriminator"] else "—",
            "EA raw": None if a["ea_raw"] is None else round(a["ea_raw"]),
            "Shift": round(a["shift_s"] or 0.0, 2),
            "Adjusted": None if a["adj"] is None else round(a["adj"], 1),
        } for a in sorted(prof["attrs"], key=lambda a: (a["bucket"], a["attribute"]))]
        st.dataframe(pd.DataFrame(arows), hide_index=True,
                     use_container_width=True, height=420)


# --- app -------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="WC2026 Match Simulator", layout="wide")

    con, P = get_setup(DEFAULT_FORMATION)
    nations = get_nations(DEFAULT_FORMATION)
    labels = get_labels()
    fmts = api.formations(con)

    def lbl(code: str) -> str:
        name = labels.get(code)
        return f"{name} ({code})" if name else code

    # Section switch: the match simulator (default) or the squad-coverage view.
    section = st.sidebar.radio(
        "Section", ["Match simulator", "Squad coverage", "Ratings audit"],
        key="section")
    if section == "Squad coverage":
        render_coverage_page(con, nations, lbl)
        return
    if section == "Ratings audit":
        render_audit_page(con, nations, lbl)
        return

    with st.sidebar:
        st.header("Match")
        a = st.selectbox("Team A (home, attacks →)", nations, format_func=lbl,
                         index=nations.index("ESP") if "ESP" in nations else 0)
        b = st.selectbox("Team B (away, attacks ←)", nations, format_func=lbl,
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

    # per-team formation: default to the auto best-fit, overridable via the panel
    # knob (st.session_state key fmt_<nation>); XI swaps live in ov[<nation>].
    auto_a, auto_b = api.auto_formation(con, a, P), api.auto_formation(con, b, P)
    fmt_a = st.session_state.setdefault(f"fmt_{a}", auto_a)
    fmt_b = st.session_state.setdefault(f"fmt_{b}", auto_b)
    ov = st.session_state.get("ov", {})

    try:
        r = api.matchup(con, a, b, P, fmt_a, fmt_b,
                        xi_a=ov.get(a), xi_b=ov.get(b))
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
    auto_fmt = auto_a if is_a else auto_b
    layout_a = api.pitch_layout(r["team_a"], view)
    layout_b = api.pitch_layout(r["team_b"], view)

    # S46 step 1b: both teams on one horizontal frame, controlled by toggles.
    tg = st.columns(6)
    show_a = tg[0].toggle(lbl(a), value=True, key="tg_show_a")
    show_b = tg[1].toggle(lbl(b), value=True, key="tg_show_b")
    show_heat = tg[2].toggle("Heatmap", value=True, key="tg_heat")
    show_zones = tg[3].toggle("Zones", value=True, key="tg_zones")
    battle = tg[4].toggle("Battle overlay", value=False, key="tg_battle",
                          help="Show A's attack vs B's defence on one frame "
                               "(overlap = contested zones) instead of one team.")
    show_strength = tg[5].toggle(
        "Zone strength", value=False, key="tg_strength",
        help="Show the 'Show team' side's team-intrinsic zone-strength map "
             "(attack or defence) on the pitch, in place of the occupancy heatmap.")
    battle_swap = False
    if battle and not show_strength:
        battle_swap = st.toggle(
            f"Swap battle: {lbl(b)} attack vs {lbl(a)} defence", value=False,
            key="tg_bswap")
    strength_profile = "attack"
    if show_strength:
        strength_profile = st.radio(
            "Strength surface", ["attack", "defence"], horizontal=True,
            format_func=str.capitalize, key="strength_profile")

    # Highlight a player via a RELIABLE picker (replaces the fragile pitch-click
    # selection — Streamlit's native Plotly selection misroutes when toggles shift
    # trace order; click-to-select is deferred to the web-app port). Drives the
    # token highlight + kernel backdrop + the Player tab.
    hl_opts = [("", None, "— none —")]
    for sd, lay in ((a, layout_a), (b, layout_b)):
        for t in lay:
            nm = t.get("name") or t["position_code"]
            hl_opts.append((sd, t["slot_no"], f"{lbl(sd)} · {nm} ({t['position_code']})"))
    pick = st.selectbox("Highlight player", hl_opts, format_func=lambda o: o[2],
                        key="hl_pick")
    sel_side, sel_slot = (pick[0] or None), pick[1]

    # Zone-battle selection — controls sit above the pitch so the on-pitch kernel
    # highlight can render this run; the breakdown table is drawn below the pitch.
    zbc = st.columns([0.34, 0.46, 0.20])
    zb_swap = zbc[0].toggle(f"Swap ({lbl(b)} attack)", key="zb_swap")
    t_att, t_def = (r["team_b"], r["team_a"]) if zb_swap else (r["team_a"], r["team_b"])
    n_att, n_def = (lbl(b), lbl(a)) if zb_swap else (lbl(a), lbl(b))
    att_side, att_up = (b, False) if zb_swap else (a, True)
    def_side, def_up = (a, True) if zb_swap else (b, False)
    zb_occ = {z: sum(c["weight"] for c in t_att["boards"]["attack"].get(z, []))
              for z in range(api.N_BANDS * api.N_LANES)}
    # "— none —" (None) first + defaulted to, so the pitch keeps its normal surface
    # until a zone is deliberately picked.
    zb_opts = [None] + [z for z in sorted(zb_occ, key=lambda z: -zb_occ[z])
                        if zb_occ[z] > 0.05]

    def _zlabel(z):
        if z is None:
            return "— none —"
        bd, ln = divmod(z, api.N_LANES)
        return f"B{bd + 1}·L{ln} · occ {zb_occ[z]:.2f}"

    # When the Zone-strength surface is switched OFF, reset the zone-battle
    # selection to "— none —" (they're used together; avoids a stale highlight
    # lingering once you leave zone-strength mode). Also guard against a persisted
    # zone that's no longer an option (e.g. after a swap changes the attacker).
    if st.session_state.get("_zb_prev_strength", show_strength) and not show_strength:
        st.session_state["zb_zone"] = None
    st.session_state["_zb_prev_strength"] = show_strength
    if st.session_state.get("zb_zone") not in zb_opts:
        st.session_state["zb_zone"] = None
    zsel = zbc[1].selectbox(f"Zone battle — {n_att} attack vs {n_def} defence",
                            zb_opts, format_func=_zlabel, key="zb_zone")
    zb_on = zbc[2].toggle("On pitch", value=True, key="zb_pitch",
                          help="When a zone is picked, highlight its top-3 players "
                               "per team with their kernels (warm A / cool B), at "
                               "attack/defence positions; overrides the surface.")
    zb_detail, zone_hi, hi_zone = None, None, None
    if zsel is not None:
        zb_detail = api.zone_battle_detail(con, t_att, t_def, zsel)
        hi_zone = (zsel, att_up)        # outline the inspected cell (kernels or not)
        if zb_on:
            atk = [p["slot_no"] for p in zb_detail["attacker"]["players"][:3]
                   if p["slot_no"] is not None]
            dfd = [p["slot_no"] for p in zb_detail["defender"]["players"][:3]
                   if p["slot_no"] is not None]
            zone_hi = {
                "att": {"team": t_att, "side": att_side, "up": att_up,
                        "slots": atk, "view": "attack", "scheme": "warm"},
                "def": {"team": t_def, "side": def_side, "up": def_up,
                        "slots": dfd, "view": "defense", "scheme": "cool"}}

    with st.expander("⚙️ Pitch appearance"):
        ac = st.columns(5)
        pitch_color = ac[0].color_picker("Pitch", PITCH, key="ap_pitch")
        col_a = ac[1].color_picker("Team A tokens", RADAR_A, key="ap_a")
        col_b = ac[2].color_picker("Team B tokens", RADAR_B, key="ap_b")
        surf_alpha = ac[3].slider("Heat opacity", 0.0, 0.9, 0.55, 0.05, key="ap_alpha")
        surf_gamma = ac[4].slider(
            "Heat contrast", 0.3, 2.5, 1.0, 0.1, key="ap_gamma",
            help="Higher = sharper peaks (suppresses the low-occupancy wash).")
        fade_alpha = st.slider("Dim non-selected players", 0.05, 1.0, 0.25, 0.05,
                               key="ap_fade")
        st.caption("Surfaces use fixed warm (Team A) / cool (Team B) gradients for "
                   "readability; the colour pickers tint the player tokens.")
    rgb_a, rgb_b = _hex_to_rgb(col_a), _hex_to_rgb(col_b)

    # Zone-strength surface for the 'Show team' side (mutually exclusive with the
    # occupancy heatmap — takes precedence in draw_pitch). 6x5 band×lane grid,
    # MIN-MAX stretched to 0-1 (weakest occupied zone -> cold, strongest -> hot)
    # because raw mean ratings are compressed; unoccupied/below-floor -> nan (drawn
    # as transparent grass, not cold fill).
    # Zone strengths for the SHOWN team (live, reflects swaps + matches the tokens).
    zs = api.zone_strengths_for_team(con, team)
    strength_grid = None
    if show_strength:
        if zs:
            vals = zs[strength_profile]
            present = [v for v in vals.values() if v is not None]
            if present:
                vmin, vmax = min(present), max(present)
                rng = (vmax - vmin) or 1.0
                def _cell(z):
                    v = vals.get(z)
                    return np.nan if v is None else (v - vmin) / rng
                strength_grid = np.array(
                    [[_cell(b * api.N_LANES + l) for l in range(api.N_LANES)]
                     for b in range(api.N_BANDS)])

    fig = draw_pitch(
        r["team_a"], r["team_b"], view, side_a=a, side_b=b, surface_side=side,
        show_a=show_a, show_b=show_b, show_heat=show_heat, show_zones=show_zones,
        battle=battle, battle_swap=battle_swap,
        sel_side=sel_side, sel_slot=sel_slot,
        pitch_color=pitch_color, rgb_a=rgb_a, rgb_b=rgb_b,
        surf_alpha=surf_alpha, surf_gamma=surf_gamma, fade_alpha=fade_alpha,
        strength_grid=strength_grid,
        strength_scheme="warm" if strength_profile == "attack" else "cool",
        zone_hi=zone_hi, hi_zone=hi_zone)
    st.plotly_chart(fig, use_container_width=True, key="pitch")
    if zone_hi:
        st.caption(f"**Zone battle highlight** — top-3 by occupancy: {n_att} attack "
                   f"(warm) vs {n_def} defence (cool) for the selected zone. "
                   "Overrides the occupancy/strength surface while 'On pitch' is on.")
    elif show_strength:
        st.caption(f"**Zone strength** — {lbl(side)}'s {strength_profile} map: "
                   "mean rating of each zone's occupants (warm = attack, cool = "
                   "defence). Shading **min–max stretched** within this team "
                   "(palest = their weakest occupied zone, fullest = strongest); "
                   "blank = zones they don't occupy. Occupancy heatmap / battle "
                   "overlay are suppressed while this is on.")
    elif battle:
        atk, dfn = (lbl(b), lbl(a)) if battle_swap else (lbl(a), lbl(b))
        st.caption(f"**Battle overlay** — {atk}'s attack (warm) vs {dfn}'s defence "
                   "(cool) on the shared frame; overlap = the contested zones.")
    else:
        st.caption(f"Heatmap = **{lbl(side)}**'s occupancy (the 'Show team' side); "
                   "both teams' tokens are shown. A selected player's kernel "
                   "replaces it.")

    # selected player's profile, from whichever team owns the selection
    sel_layout = (layout_a if sel_side == a else layout_b if sel_side == b else None)
    sel_tok = (next((t for t in sel_layout if t["slot_no"] == sel_slot), None)
               if sel_layout else None)
    sel_team = (r["team_a"] if sel_side == a else r["team_b"] if sel_side == b
                else None)
    srid = (sel_team.get("sid", {}).get(sel_slot)
            if sel_team is not None and sel_slot is not None else None)
    profile = (api.player_profile(con, srid, sel_tok.get("ea_id"))
               if sel_tok is not None else None)

    # info panel (4 tabs); follows the sidebar "Show team" for Team/Player, but
    # Zone battle + Probability are two-team. Strategy + scoreline now live in tabs.
    render_panel(con, team, view, lbl(side), side, fmts, auto_fmt, P,
                 r["team_a"], r["team_b"], lbl(a), lbl(b), sel_tok, profile, zs,
                 zb_detail=zb_detail, n_att=n_att, n_def=n_def,
                 matrix=r["matrix"], code_a=a, code_b=b)


if __name__ == "__main__":
    main()
