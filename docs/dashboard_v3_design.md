# Dashboard V3 — Visuals + Team/Player Stats (Design)

> Design-before-code doc for the S45 dashboard work. Companion to
> `docs/dashboard_design.md` (the V0–V2 engineering record); this doc covers the
> V3 increment only. Live element tracker stays in Notion → **Dashboard Tracker**.
> Decisions here were agreed with Indraneel in S45 before any code was written.

## 0. Scope

Six pieces, built in sequence (small + shippable, not one blob). Two are pitch
visuals, four are stats/interaction. Agreed order:

1. This design doc.
2. Info panel → **tabs** (Team / Player) + **radar chart** (both teams overlaid).
3. **Player clickability** — native Plotly selection + highlight/fade.
4. **Player stats tab** content — positions, playstyles, ratings, top-5 attrs.
5. **Two-team overlaid zonal-battle heatmap** (red/blue, shared frame).
6. **Team stats zone strengths/weaknesses** (Σ occupancy × rating).

The model is **not** rewritten. As in V1/V2, every new view reads through
`dashboard/model_api.py`; the Streamlit view (`dashboard/app.py`) stays
presentation-only. New data the view needs is added as adapter functions, not
inline SQL in the view.

## 1. Key decisions (agreed S45)

### 1.1 Clickability uses native Streamlit selection — no third-party component

`pyproject.toml` pins `streamlit>=1.58.0`. Native chart selection
(`st.plotly_chart(on_select="rerun", selection_mode="points")`) has existed since
1.35, so the fragile `streamlit-plotly-events` component is **not** needed. A
click on a player token returns the selected point index; the view maps that to a
`slot_no` and stores it in `st.session_state` (`sel_<nation>`). The pitch then
re-renders with that token highlighted and the rest faded, and the Player tab
reads the selection.
Ref: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart

Token trace is a single `go.Scatter`; selection point index == token order in
`pitch_layout`, so index→slot is a direct lookup (no ambiguity from the
heatmap/lines traces — those carry `hoverinfo="skip"` and aren't selectable).

### 1.2 Overlaid heatmap — shared frame, curated default, free combos allowed

The V1 pitch draws one team oriented to attack up/down. Overlaying both teams
requires a **single shared coordinate frame**, which means **mirroring Team B**
(it attacks the opposite direction). Consequence: not all 4×4 profile pairs are
physically meaningful — A-attack vs B-attack on a shared pitch is two teams
wanting the same grass from opposite ends, not a battle.

**Decision:** support any per-team profile choice (free combos), but **default to
the meaningful battle**: **A attack (red) vs B defense (blue)**, with a swap to
B-attack-vs-A-defense. Label it explicitly as a battle view so a free combo can't
be silently misread.

- Colours: red = Team A surface, blue = Team B surface, additive translucent fill
  over the green pitch; overlap reads purple. Each surface normalised to its own
  max so neither washes out.
- Tokens/lines made translucent in this view (clutter reduction, per spec).
- Orientation: reuse the existing `_vmap(..., up=...)`; Team B's grid is placed
  with `up=False` so its bands mirror onto A's frame.

### 1.3 Team stats tab is inherently two-team

The radar overlays both teams, and zone strengths compare both, so the **Team
tab always shows both teams** even though the pitch panel still shows one selected
side. This is a deliberate shift from the V2 single-team panel.

### 1.4 Radar replaces the 5 progress bars

The 5 playstyle axes (`possession, line_height, ppda, width, directness`, all
0–1 percentiles, already on `team["axes"]`) become a single `go.Scatterpolar`
with two traces (red A / blue B). No new data — pure re-render of `axes`.

## 2. Per-step data contract (what each step needs from model_api)

| Step | New / changed adapter | Source already in repo? |
|---|---|---|
| 2 radar | none (uses `team["axes"]`) | ✅ `assemble_team` returns `axes` |
| 3 select | none (view-state only) | ✅ `pitch_layout` order is stable |
| 4 player | `player_profile(con, nation, ea_id/sid)` → positions, playstyles, overall, attr list | positions: `squad_position_eligibility`; attrs: `player_adjusted_attributes_wide` / long; EA playstyles + overall: `ea_fc26_player` — **to confirm exact columns at step 4** |
| 5 overlay | `team_heatmap` already returns the 6×5 grid per view; view mirrors B | ✅ `team_heatmap(team, view)` |
| 6 zones | `zone_strengths(team)` → top/bottom 3 attack & defence zones by Σ(occupancy × rating) | **needs read of `zone_aggregate.py` / `zone_battle.py` — see §3** |

## 3. Open question parked for step 6 (zone strengths)

Spec: rank pitch zones by **Σ over players of (occupancy in zone × player rating
on the zone-relevant attributes)** — top 3 attack zones (attack profile) and top 3
defence zones (defence profile) as *strengths*; the bottom 3 of each as
*weaknesses*.

Before building, confirm against the model (observe, don't infer):

1. Does the zone-battle layer already compute a per-zone strength value
   (`zone_aggregate.py` / `zone_battle.py`), or only an aggregated team index?
   If per-zone strengths exist, surface them; if only the index exists, assemble
   the Σ from `slots[*].attack_grid/defence_grid` (occupancy) × the bucketed
   adjusted ratings.
2. What is the zone→attribute mapping (which EA attributes count toward a zone's
   attack vs defence strength)? If `zone_battle` already defines it, reuse it
   verbatim — do **not** invent a second mapping.
3. The current `strategy_notes` strengths/weaknesses are derived from the 5 axes,
   not zones. Decide: does the zone view **replace** that text, or sit beside it?

These are resolved at step 6, not now, to avoid guessing model internals.

## 3a. S45 finding — derived single-rating scalar is misleading (step 4)

The Player tab's "Adj rating" (option 1&3) was defined as the **mean of `adj`
over a player's discriminator attributes**. Observed in the live UI: Lamine Yamal
64.7 vs Jordan Henderson 71.6 — a flat mean flattens specialists (a winger's
discriminator set spans buckets he's naturally weak in) and rewards balanced
midfielders. This is a summary artifact, NOT evidence the adjusted *attributes*
are wrong.

**RESOLVED (S45).** Probe of Yamal's rows confirmed the pipeline is sound: his
Attack bucket shifted **+6.27** (finishing 83→89, long_shots 82→88), Possession
−0.76, Defense 0. The shift is **uniform within a bucket** (per-phase, not
per-attribute). Fix shipped: removed the single scalar (EA `ovr` is already a
position-weighted overall); the Player tab now shows the **per-phase shift** as
the honest "what the empirical data did" summary. Still wanted: a dedicated
**ratings-audit page** (step 4b) to scan all players' raw→adj + the empirical
drivers behind each shift.

## 5. Step 4b — ratings-audit page (design)

Goal: verify the adjustment pipeline and show, per player, the empirical data that
moved each rating. Driver chain (read from `_probe_adjusted_ratings.build` +
`derive_adjusted_attributes`):

    adjusted_pct_d = (1−λ_d)·EA_role_pct_d + λ_d·empirical_pct_d
    λ_d = min(minutes_d/900, 1)·CAP_d     CAP Attack .60 / Poss .50 / Def .25; off-role→0
    empirical: Attack=(g+xa)/90 [Understat]; Possession=(kp+xg_buildup+xg_chain)/90
               [Understat]; Defense=0.6·padj+0.4·suppression [FBref]
    shift_s_d = (rating@adj_pct − ea_d)/BASE_W ; attr adj = clip(ea_raw + shift_s_d)

**Data-sourcing decision:** the per-dim intermediates (EA pct, empirical pct, λ,
Δ, raw stats) are NOT persisted — only `adj_pct`/`lambda_dim`/`shift_s` are. So the
audit calls the canonical engine **`_probe_adjusted_ratings.build(con)` live**
(read-only, built for reuse), wrapped in a model_api adapter + `st.cache_data`.
Rationale: single source of truth — the audit shows the model's exact math, no
re-implementation drift. Cost: one all-player build per session (cached).

**OPEN — verify before coding:** `build()` reads raw match tables
(`player_match_stats`, `player_match_fbref`, `team_match_fbref`, `players`). The
dashboard defaults to the trimmed `worldcup_dashboard.duckdb`; if those tables were
excluded by `make_dashboard_db`, the audit must open the FULL `worldcup.duckdb`
instead. Check table availability first.

**Page layout** (new sidebar Section "Ratings audit"):
- nation + player pickers.
- per-dimension blend table: dim | EA pct | empirical pct | λ (minutes, CAP) |
  blended pct | Δpct | shift_s — the explanation of every shift.
- empirical inputs + competition backing: raw stats per dim, plus league/season/
  matches/minutes from the source tables, mapped League/Continental/International,
  de-duplicated (fixes the Player-tab provider-sum double-count).
- attribute table: raw EA → adj, all attrs grouped by bucket.
- optional nation scan: EA over/under-rated leaderboard (top Δ per dim).

**Open decisions:** (a) include the nation-scan leaderboard? (b) league→category
mapping — enumerate distinct `league` values first.

## 4. Non-goals / guardrails

- No model logic changes; no new DB tables expected (all reads).
- Keep `model_api.py` Streamlit-agnostic (CLI self-test must still run).
- Caching unchanged: selection and tab state are session state, not cache keys,
  so they don't bust the cached assembly.
