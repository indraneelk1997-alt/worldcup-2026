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
from functools import lru_cache
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
    _scoreline_setup, autopick_xi, load_gk_score, SLOT_GROUP,
    _lambda_pair, bivariate_poisson_matrix, _matrix_summary,
    best_formation, slot_alternatives,
)
from src.load.v2_ingest.formation_assembly import assemble, team_boards  # noqa: E402
from src.load.v2_ingest.kernel_transforms import (       # noqa: E402
    N_BANDS, N_LANES, _centroid_band, _centroid_lane)
import _probe_adjusted_ratings as _blend_eng              # noqa: E402  canonical blend engine

PITCH_LEN, PITCH_WID = 120.0, 80.0        # StatsBomb pitch; own goal x=0, attack x=120

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


def formations(con) -> list[str]:
    """All formation codes the model knows (the formation-knob dropdown options)."""
    return [r[0] for r in con.execute(
        "SELECT formation FROM formations ORDER BY formation").fetchall()]


def auto_formation(con, nation: str, P: dict) -> str:
    """The best-fit formation for a squad (item 9 best_formation) -- the dropdown
    default. Cheap: assignment-fit over the candidate shapes."""
    return best_formation(con, nation, P["scores"])[0]


def alternatives(con, nation: str, formation: str, slot_no: int, P: dict,
                 exclude_ea: tuple = ()) -> list[tuple]:
    """Eligible swap candidates for one slot, ranked best-fit first (the swap
    dropdown). -> [(ea_id, squad_row_id, name, score, fit)]."""
    row = con.execute("SELECT position_code FROM formation_slots "
                      "WHERE formation=? AND slot_no=?", [formation, slot_no]).fetchone()
    if not row:
        return []
    return slot_alternatives(con, nation, row[0], P["scores"], tuple(exclude_ea))


def assemble_team(con, nation: str, P: dict, formation: str = DEFAULT_FORMATION,
                  xi_override: dict | None = None):
    """Auto-pick the best XI -> full team bundle for the dashboard.

    Richer than the model's _assemble_team: also keeps the player NAMES and the
    {slot: ea_id} XI dict (both needed by the view / the V2 swap path). Keeps the
    `gk` (score) and `boards` keys exactly as the model's downstream functions
    (_lambda_pair / compute_attack_index) expect them, so this dict is a valid
    input to those.  Returns None if the squad can't be assembled.

      -> {nation, formation, sid, names, xi_ea, slots, axes, boards, gk, gk_name}

    `slots` (the per-slot 6x5 attack/defence grids) and `axes` (team playstyle,
    incl. possession) are kept so the pitch view can place tokens at each
    player's blended-grid centroid. `boards` stays for the scoreline path.
    """
    xi_ea, sid, names = autopick_xi(con, nation, formation, P["scores"])
    if not sid:
        return None
    if xi_override:                          # V2 swap: override slots, refresh meta
        for slot_no, ea in xi_override.items():
            if ea is None or slot_no not in xi_ea:
                continue
            row = con.execute(
                "SELECT squad_row_id, player_name FROM wc2026_squad "
                "WHERE ea_id=? AND nation_code=?", [ea, nation]).fetchone()
            if row:
                xi_ea[slot_no], sid[slot_no], names[slot_no] = ea, row[0], row[1]
    axes, slots = assemble(con, formation, nation, P["cfg"], P["fwd"], xi=xi_ea)
    gk_score, gk_name = load_gk_score(con, nation)
    # EA overall ('ovr') for the XI + the GK, for the token brackets / info panel.
    ids = list(xi_ea.values())
    ovr = {}
    if ids:
        ph = ",".join("?" * len(ids))
        ovr = dict(con.execute(
            f"SELECT ea_id, ovr FROM ea_fc26_player WHERE ea_id IN ({ph})", ids).fetchall())
    gkr = con.execute(
        "SELECT e.ovr FROM wc2026_squad s JOIN ea_fc26_player e ON e.ea_id=s.ea_id "
        "WHERE s.nation_code=? AND s.primary_position_group='GK' "
        "ORDER BY s.caps DESC LIMIT 1", [nation]).fetchone()
    return {"nation": nation, "formation": formation, "sid": sid, "names": names,
            "xi_ea": xi_ea, "slots": slots, "axes": axes, "ovr": ovr,
            "gk_ovr": gkr[0] if gkr else None,
            "boards": team_boards(slots), "gk": gk_score, "gk_name": gk_name}


def matchup(con, nation_a: str, nation_b: str, P: dict,
            formation_a: str = DEFAULT_FORMATION, formation_b: str | None = None,
            l3: float = 0.0, xi_a: dict | None = None,
            xi_b: dict | None = None) -> dict:
    """Full A-vs-B result for the dashboard: assemble both XIs -> lambda-means
    -> bivariate-Poisson scoreline matrix + W/D/L summary. Each team can take its
    own formation + XI override (the V2 formation knob / player swap).

    Rows of `matrix` = team_a goals, cols = team_b goals (so summary['p_home']
    is team_a's win prob). Raises ValueError if either side can't be assembled.

      -> {team_a, team_b, lam_a, lam_b, matrix, summary}
    """
    formation_b = formation_b or formation_a
    ta = assemble_team(con, nation_a, P, formation_a, xi_a)
    tb = assemble_team(con, nation_b, P, formation_b, xi_b)
    if ta is None or tb is None:
        raise ValueError(f"could not assemble {nation_a if ta is None else nation_b}")
    lam_a, lam_b = _lambda_pair(con, ta, tb, P)
    l1, l2 = max(lam_a - l3, 0.0), max(lam_b - l3, 0.0)
    M = bivariate_poisson_matrix(l1, l2, l3)
    return {"team_a": ta, "team_b": tb, "lam_a": lam_a, "lam_b": lam_b,
            "matrix": M, "summary": _matrix_summary(M)}


# --------------------------------------------------------------------------- #
# Pitch view (V1): four placement modes per team.
#   standard   -> textbook formation anchors (position_home_cells.json)
#   possession -> centroid of p*attack + (1-p)*defence (default)
#   attack     -> centroid of the attack-phase grid
#   defense    -> centroid of the defence-phase grid
# --------------------------------------------------------------------------- #
VIEWS = ("standard", "possession", "attack", "defense")


@lru_cache(maxsize=1)
def _home_anchors() -> dict:
    """position_code -> (band_pos, lane_pos) textbook anchor for the 'standard'
    view (data/config/position_home_cells.json, chessboard item 2)."""
    raw = json.loads((_ROOT / "data" / "config" / "position_home_cells.json")
                     .read_text(encoding="utf-8"))["anchors"]
    return {pc: (a["band_pos"], a["lane_pos"]) for pc, a in raw.items()}


def _blended_grid(slot: dict, p: float):
    """p*attack + (1-p)*defence for one slot (both are 6x5 numpy grids)."""
    return p * slot["attack_grid"] + (1.0 - p) * slot["defence_grid"]


def _band_lane_to_xy(band: float, lane: float) -> tuple[float, float]:
    """6x5 band/lane -> pitch (x, y). Band 0 = own goal (x~10), band 5 =
    attacking goal (x~110). Lane is INVERTED on y so the convention matches a
    side attacking left->right: lane 0 (left flank) -> high y (top), lane 4
    (right flank) -> low y (bottom). Heatmap is reversed to match (app.py)."""
    return ((band + 0.5) / N_BANDS * PITCH_LEN,
            (N_LANES - lane - 0.5) / N_LANES * PITCH_WID)


def _slot_band_lane(slot: dict, view: str, p: float):
    """Where a slot's token sits, per view. 'standard' = textbook anchor (+ the
    lateral-fan offset for duplicated central codes); the others = centroid of
    the attack / defence / possession-blended grid."""
    if view == "standard":
        ab, al = _home_anchors()[slot["position_code"]]
        return ab, al + slot["fan_lane"]
    g = (slot["attack_grid"] if view == "attack"
         else slot["defence_grid"] if view == "defense"
         else _blended_grid(slot, p))
    return _centroid_band(g), _centroid_lane(g)


def pitch_layout(team: dict, view: str = "possession") -> list[dict]:
    """Token per player for one of the four VIEWS. GK is always parked at its
    deep-central anchor (it has no occupancy grid).
      -> [{slot_no, name, position_code, group, ea_id, ovr, x, y, band, lane,
           budget, mv_tags}]
    """
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}, got {view!r}")
    p = float(team["axes"]["possession"])
    ovr_map = team.get("ovr", {})
    out = []
    for s in team["slots"]:
        pc = s["position_code"]
        if s["attack_grid"] is None:                    # GK (no kernel) -> anchor
            ab, al = _home_anchors().get(pc, (0.0, 2.0))
            x, y = _band_lane_to_xy(ab, al)
            out.append({"slot_no": s["slot_no"], "name": team.get("gk_name"),
                        "position_code": pc, "group": "GK", "ea_id": None,
                        "ovr": team.get("gk_ovr"), "x": x, "y": y,
                        "band": ab, "lane": al, "budget": 0.0, "mv_tags": []})
            continue
        name = team["names"].get(s["slot_no"])
        if name is None:                                # unfilled outfield slot
            continue
        cb, cl = _slot_band_lane(s, view, p)
        x, y = _band_lane_to_xy(cb, cl)
        out.append({"slot_no": s["slot_no"], "name": name, "position_code": pc,
                    "group": SLOT_GROUP.get(pc, "MID"), "ea_id": s["ea_id"],
                    "ovr": ovr_map.get(s["ea_id"]), "x": x, "y": y,
                    "band": cb, "lane": cl,
                    "budget": float(_blended_grid(s, p).sum()), "mv_tags": s["mv_tags"]})
    return out


def team_heatmap(team: dict, view: str = "possession"):
    """Team occupancy backdrop (6x5). attack/defense -> that phase's sum; else
    the possession-blended sum ('standard' uses the blended surface)."""
    import numpy as np
    p = float(team["axes"]["possession"])
    grid = np.zeros((N_BANDS, N_LANES))
    for s in team["slots"]:
        if s["attack_grid"] is None:
            continue
        grid += (s["attack_grid"] if view == "attack"
                 else s["defence_grid"] if view == "defense"
                 else _blended_grid(s, p))
    return grid


def player_kernel(team: dict, slot_no, view: str = "possession"):
    """6x5 occupancy grid for ONE player's slot, per view (attack/defense/blended-
    possession). Returns None for the GK or an unknown slot (no kernel) so the
    caller can keep the team backdrop. Used when a selected player's kernel
    replaces the team heatmap on the pitch (V3 step 4)."""
    if slot_no is None:
        return None
    p = float(team["axes"]["possession"])
    for s in team["slots"]:
        if s["slot_no"] != slot_no:
            continue
        if s["attack_grid"] is None:                 # GK — no kernel
            return None
        if view == "attack":
            return s["attack_grid"]
        if view == "defense":
            return s["defence_grid"]
        return _blended_grid(s, p)                    # standard/possession
    return None


def strategy_notes(team: dict) -> dict:
    """Deterministic, explainable strengths/weaknesses from the 5 playstyle axes
    (all 0..1 percentiles) + a one-line style tag. No black box -- pure rules.
      -> {summary, strengths: [...], weaknesses: [...]}"""
    ax = team["axes"]
    poss, line = float(ax["possession"]), float(ax["line_height"])
    press, width, direct = float(ax["ppda"]), float(ax["width"]), float(ax["directness"])

    def lvl(v):
        return "high" if v >= 0.66 else "low" if v <= 0.34 else "mid"

    S, W = [], []
    if lvl(poss) == "high":
        S.append("Controls the ball and dictates tempo.")
    elif lvl(poss) == "low":
        S.append("Comfortable without the ball; soaks up pressure.")
        W.append("Cedes possession and territory.")
    if lvl(line) == "high":
        S.append("High line compresses the pitch and pins opponents back.")
        W.append("Space in behind — vulnerable to pace and through-balls.")
    elif lvl(line) == "low":
        S.append("Deep, compact block — hard to break down centrally.")
        W.append("Invites sustained pressure; little territory.")
    if lvl(press) == "high":
        S.append("Aggressive high press to win the ball early.")
        W.append("If the press is beaten, large gaps open up.")
    elif lvl(press) == "low":
        S.append("Holds shape and conserves energy.")
        W.append("Gives opponents time to build unopposed.")
    if lvl(width) == "high":
        S.append("Stretches play and attacks through the flanks.")
    elif lvl(width) == "low":
        S.append("Narrow shape congests the central zones.")
        W.append("Little natural width to stretch a set block.")
    if lvl(direct) == "high":
        S.append("Direct and vertical — fast in transition.")
    elif lvl(direct) == "low":
        S.append("Methodical, patient build-up.")

    style = ("Possession" if lvl(poss) == "high"
             else "Counter-attacking" if lvl(poss) == "low" else "Balanced")
    shape = ("high press" if lvl(press) == "high"
             else "low block" if lvl(line) == "low" else "measured pressing")
    return {"summary": f"{style} side, {shape}.", "strengths": S, "weaknesses": W}


# --------------------------------------------------------------------------- #
# Squad coverage (reads player_coverage_index; docs/player_coverage_index.md).
# Read-only display data for the "Squad coverage" page + future profile visuals.
# --------------------------------------------------------------------------- #
_GRP_ORDER = ("CASE primary_position_group WHEN 'GK' THEN 0 WHEN 'DEF' THEN 1 "
              "WHEN 'MID' THEN 2 WHEN 'FWD' THEN 3 ELSE 4 END")

# tier -> (label, hex) for badge rendering. Mirrors the design-doc ladder.
COVERAGE_TIERS = {
    "empirical+rated":   ("Empirical + rated", "#15803d"),
    "rated":             ("Rated (EA-adjusted)", "#4ade80"),
    "empirical_unrated": ("Empirical, unrated", "#f97316"),
    "ea_only":           ("EA only", "#f59e0b"),
    "group_only":        ("Group fallback", "#dc2626"),
    "none":              ("No data", "#9ca3af"),
    "gk":                ("Goalkeeper", "#64748b"),
}


def coverage_rows(con, nation: str) -> list[dict]:
    """All squad players for a nation with their coverage signals, ordered
    GK->DEF->MID->FWD then best-covered first. One dict per player."""
    cur = con.execute(f"""
        SELECT player_name, primary_position_group AS grp, caps, club,
               coverage_tier, coverage_score, has_ea, has_adjusted, coverage_basis,
               understat_minutes, understat_matches, fbref_minutes, fbref_matches,
               statsbomb_minutes, statsbomb_matches,
               empirical_minutes_total, n_empirical_sources
        FROM player_coverage_index WHERE nation_code = ?
        ORDER BY {_GRP_ORDER}, coverage_score DESC NULLS LAST, caps DESC NULLS LAST
    """, [nation])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def coverage_rating(con, nation: str) -> dict:
    """Team coverage headline (outfield-only; GKs excluded from both numbers, as
    they're rated separately and carry a NULL coverage_score).
      -> {n_squad, n_outfield, pct_ready, weighted, tier_counts}"""
    r = con.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE primary_position_group <> 'GK'),
               AVG(CASE WHEN primary_position_group <> 'GK'
                        THEN CASE WHEN has_adjusted THEN 1.0 ELSE 0.0 END END),
               AVG(coverage_score)
        FROM player_coverage_index WHERE nation_code = ?
    """, [nation]).fetchone()
    tc = dict(con.execute("""
        SELECT coverage_tier, COUNT(*) FROM player_coverage_index
        WHERE nation_code = ? GROUP BY 1""", [nation]).fetchall())
    return {"n_squad": r[0], "n_outfield": r[1],
            "pct_ready": (r[2] or 0.0) * 100.0,
            "weighted": (r[3] or 0.0) * 100.0, "tier_counts": tc}


def coverage_nations(con) -> list[dict]:
    """All nations ranked by outfield coverage -- for a league-table overview.
      -> [{nation, pct_ready, weighted, n}] best-first."""
    cur = con.execute(f"""
        SELECT nation_code,
               100.0*AVG(CASE WHEN primary_position_group <> 'GK'
                              THEN CASE WHEN has_adjusted THEN 1.0 ELSE 0.0 END END) AS pct_ready,
               100.0*AVG(coverage_score) AS weighted, COUNT(*) AS n
        FROM player_coverage_index GROUP BY 1
        ORDER BY pct_ready DESC, weighted DESC""")
    return [{"nation": a, "pct_ready": b, "weighted": c, "n": d}
            for a, b, c, d in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Player profile (the Player tab, V3 step 4). One call, several tables; any of
# squad_row_id / ea_id may be None (GK or unrated) -> sections degrade cleanly.
# --------------------------------------------------------------------------- #
_FACE = [("PAC", "ea_pace"), ("SHO", "ea_shooting"), ("PAS", "ea_passing"),
         ("DRI", "ea_dribbling"), ("DEF", "ea_defending"), ("PHY", "ea_physical")]


def player_profile(con, squad_row_id, ea_id) -> dict:
    """Everything the Player tab renders, in one read:
      - EA identity: overall, primary/alt position, age, club, foot, 6 face stats
      - playstyles (ea_fc26_playstyle: name + tier)
      - empirical positions (squad_position_eligibility: role/share/modal/eligible)
      - adjusted attributes (player_adjusted_attributes: ea_raw + adj + shift, adj-desc)
      - coverage row (player_coverage_index: tier + per-source minutes)

    Note: there is deliberately NO single 'adjusted overall' scalar. EA's own
    `ovr` is already a position-weighted overall; a flat mean over attributes
    flattens specialists (S45: Yamal 64.7 < Henderson 71.6), so the per-phase
    shift (uniform within a bucket) is the honest summary instead.
    """
    prof = {"overall": None, "ea_position": None, "alt_positions": None,
            "age": None, "club": None, "foot": None, "face": [],
            "playstyles": [], "positions": [], "attrs": [], "coverage": None}

    if ea_id:
        cols = "ovr, position, alt_positions, age, club, preferred_foot, " \
               + ", ".join(c for _, c in _FACE)
        ea = con.execute(f"SELECT {cols} FROM ea_fc26_player WHERE ea_id=?",
                         [ea_id]).fetchone()
        if ea:
            prof.update(overall=ea[0], ea_position=ea[1], alt_positions=ea[2],
                        age=ea[3], club=ea[4], foot=ea[5])
            prof["face"] = [(lab, ea[6 + i]) for i, (lab, _) in enumerate(_FACE)]
        prof["playstyles"] = [
            {"playstyle": p, "tier": t} for p, t in con.execute(
                "SELECT playstyle, tier FROM ea_fc26_playstyle WHERE ea_id=? "
                "ORDER BY CASE tier WHEN 'plus_plus' THEN 0 WHEN 'plus' THEN 1 "
                "ELSE 2 END, playstyle", [ea_id]).fetchall()]

    if squad_row_id is not None:
        prof["positions"] = [
            {"role": r[0], "minutes": r[1], "share": r[2], "is_modal": r[3],
             "eligible": r[4], "basis": r[5]} for r in con.execute(
                "SELECT role, minutes, minutes_share, is_modal, eligible, basis "
                "FROM squad_position_eligibility WHERE squad_row_id=? "
                "ORDER BY minutes_share DESC NULLS LAST", [squad_row_id]).fetchall()]
        prof["attrs"] = [
            {"attribute": a[0], "bucket": a[1], "ea_raw": a[2], "adj": a[3],
             "shift_s": a[4], "is_discriminator": a[5]} for a in con.execute(
                "SELECT attribute, bucket, ea_raw, adj, shift_s, is_discriminator "
                "FROM player_adjusted_attributes WHERE squad_row_id=? "
                "ORDER BY adj DESC NULLS LAST", [squad_row_id]).fetchall()]
        cov = con.execute(
            "SELECT coverage_tier, understat_minutes, fbref_minutes, "
            "statsbomb_minutes, empirical_minutes_total, coverage_score "
            "FROM player_coverage_index WHERE squad_row_id=?", [squad_row_id]).fetchone()
        if cov:
            prof["coverage"] = {"tier": cov[0], "understat_minutes": cov[1],
                                "fbref_minutes": cov[2], "statsbomb_minutes": cov[3],
                                "empirical_minutes_total": cov[4], "score": cov[5]}
    return prof


# --------------------------------------------------------------------------- #
# Ratings audit (V3 step 4b). Reuses the CANONICAL blend engine read-only, so the
# audit shows the model's exact math rather than a re-implementation. The engine's
# per-dim intermediates (EA pct / empirical pct / lambda / blended pct / delta /
# raw empirical stats) aren't persisted, hence the live call.
# --------------------------------------------------------------------------- #
def blend_frame(con):
    """The engine's per-player blend dataframe (one row per outfield squad player;
    GKs excluded by the engine). Expensive-ish (all players) -> cache upstream."""
    return _blend_eng.build(con)


def _f(v):
    """NaN/None -> None, else float (NaN != NaN). Avoids a pandas import here."""
    return None if v is None or v != v else float(v)


_AUDIT_MIN = {"Attack": "att_min", "Possession": "att_min", "Defense": "def_min"}


def player_blend(df, squad_row_id) -> dict | None:
    """Per-dimension blend breakdown for one player from blend_frame(). The exact
    inputs to each attribute shift: EA role pct, empirical pct, lambda (with the
    minutes + per-phase CAP behind it), the blended pct and its delta vs EA, plus
    the raw empirical value. -> None if the player isn't in the frame (e.g. GK)."""
    sub = df[df["squad_row_id"] == squad_row_id]
    if sub.empty:
        return None
    r = sub.iloc[0]
    dims = []
    for d in ("Attack", "Possession", "Defense"):
        dims.append({
            "dim": d,
            "ea_pct": _f(r.get(f"ea_{d}_pct")),
            "emp_pct": _f(r.get(f"emp_{d}_pct")),
            "lam": _f(r.get(f"lam_{d}")),
            "cap": _blend_eng.CAP[d],
            "blended_pct": _f(r.get(f"adj_{d}")),
            "delta_pct": _f(r.get(f"delta_{d}")),
            "minutes": _f(r.get(_AUDIT_MIN[d])),
            "on_role": d in _blend_eng.RELEVANT.get(r["grp"], set()),
            # raw empirical value feeding the percentile (per-90 for Att/Poss)
            "empirical_value": _f(r.get(d)) if d in ("Attack", "Possession") else None,
        })
    return {"name": r["name"], "grp": r["grp"], "dims": dims,
            "padj": _f(r.get("padj")), "supp": _f(r.get("supp"))}


# --------------------------------------------------------------------------- #
# CLI self-test (no Streamlit) -- mirrors zone_aggregate.py --scoreline output.
# --------------------------------------------------------------------------- #
def _gk_str(team: dict) -> str:
    return f"{team['gk_name']} ({team['gk']:.0f})" if team.get("gk") else "none"


def _selftest(a: str = "ESP", b: str = "ENG") -> None:
    con, P = setup()
    try:
        print(f"nations available: {len(list_nations(con))}")
        fa, fb = auto_formation(con, a, P), auto_formation(con, b, P)
        print(f"auto formation: {a} {fa} | {b} {fb} | options {formations(con)}")
        r = matchup(con, a, b, P, fa, fb)
        sn = sorted(r["team_a"]["names"])[0]                 # exercise swap list
        alts = alternatives(con, a, fa, sn, P, tuple(r["team_a"]["xi_ea"].values()))
        print(f"alts for {a} slot {sn} ({r['team_a']['names'][sn]}): "
              + ", ".join(f"{x[2]}({x[4]:.2f})" for x in alts[:4]))
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


def _pitch_probe(nation: str = "ESP", view: str = "possession") -> None:
    con, P = setup()
    try:
        team = assemble_team(con, nation, P)
    finally:
        con.close()
    if not team:
        raise SystemExit(f"could not assemble {nation}")
    p = float(team["axes"]["possession"])
    print(f"{nation} {team['formation']}  view={view}  possession p={p:.3f}  "
          f"(pitch {PITCH_LEN:.0f}x{PITCH_WID:.0f})\n")
    print(f"  {'slot':>4} {'code':>4} {'grp':>4} {'ovr':>3} {'band':>5} {'lane':>5} "
          f"{'x':>6} {'y':>6}  player")
    for t in pitch_layout(team, view):
        print(f"  {t['slot_no']:>4} {t['position_code']:>4} {t['group']:>4} "
              f"{(t['ovr'] or 0):>3} {t['band']:>5.2f} {t['lane']:>5.2f} "
              f"{t['x']:>6.1f} {t['y']:>6.1f}  {t['name']}")


def _coverage_probe(nation: str = "BRA") -> None:
    con, _ = setup()
    try:
        rt = coverage_rating(con, nation)
        rows = coverage_rows(con, nation)
    finally:
        con.close()
    print(f"{nation}: {rt['n_outfield']} outfield (+GK) | model-ready "
          f"{rt['pct_ready']:.1f}% | weighted {rt['weighted']:.1f} | "
          f"tiers {rt['tier_counts']}\n")
    print(f"  {'pos':>3} {'tier':>17} {'U_min':>6} {'F_min':>6} {'S_min':>6} "
          f"{'EA':>2} {'adj':>3}  player")
    for r in rows:
        print(f"  {r['grp']:>3} {r['coverage_tier']:>17} "
              f"{r['understat_minutes']:>6} {r['fbref_minutes']:>6} "
              f"{r['statsbomb_minutes']:>6} {('Y' if r['has_ea'] else '-'):>2} "
              f"{('Y' if r['has_adjusted'] else '-'):>3}  {r['player_name']}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--pitch":
        _pitch_probe(a[1] if len(a) > 1 else "ESP",
                     a[2] if len(a) > 2 else "possession")
    elif a and a[0] == "--coverage":
        _coverage_probe(a[1] if len(a) > 1 else "BRA")
    else:
        _selftest(*(a[:2] if len(a) >= 2 else ()))
