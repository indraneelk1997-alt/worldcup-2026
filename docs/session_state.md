# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S34 (2026-06-13)
**Current version line:** **Chessboard IMPLEMENTATION — items 1–7 DONE (item 7
framework + 1 of 9 zones).** Item 6 synthesis (two phase-separated per-zone team
boards) + item 7 zone-battle framework + the **Central-L1** battle all built &
validated on real players (Kane vs Van Dijk). All lazy pure functions (decision B;
no tables). DB unchanged at **41 base tables**. Pipeline now spans
occupancy → SHIFT/TWEAK → team boards → class-clean two-stage zone battle → threat,
ready for item-8 value-weighting (`zone_xt`) + aggregation → xG. Remaining: author
the other **8 zones** (template proven, config-only), wire occupancy-weighted zone
aggregation (battle is 1v1 so far), THEN design **item 8** (carry offside gate +
transition term, both banked).

## S34 outcome — chessboard items 6 & 7 (synthesis + zone battle, Central-L1)

Implementation session, shell-relay throughout. Built item 6 (synthesis) and the
item-7 framework + its first zone, all validated on real players/output.

### Item 6 — synthesis: two phase-separated per-zone team boards (DONE)
**Decision (S34):** synthesis outputs **separate attack + defence per-zone boards**;
the **possession blend is deferred to item-8 aggregation**. Reason: contests are
directional (attacker's *attack* board vs defender's *defence* board); baking
possession `p` into the per-player board early double-uses it and blurs the two
tactical phases that never actually coexist on the pitch.
- Refactored `kernel_transforms`: **`transform_phase_grids()`** returns the two
  per-phase grids `(A, D)`, each normalised to the player's budget (`availability`);
  `transform_kernel()` is now a thin possession-blend convenience (viz only).
- `formation_assembly`: `assemble()` stores per-slot `attack_grid`+`defence_grid`;
  **`team_boards()`** inverts the per-slot grids into `{attack, defence}` boards,
  each `zone_id → [(slot, position_code, ea_id, weight)]` sorted. Per-slot grids
  stay the source of truth (item 7). `--demo` validated: ESP 4-2-3-1 attack board
  advanced/narrow/half-space-heavy (Spain shape), defence board deeper/compact; the
  **ST sits higher in defence than attack** (high press) — only the phase split
  shows it. Board sum = team budget (~1000%, +25% with Relentless availability).

### Item 7 — zone-battle attribute relevance + resolution (framework + Central-L1)
Design: **`docs/item7_zone_battle.md`**.
- **9 zones** = 3 lane-types × 3 goal-relative band-levels (mirror-folded `B1↔B6,
  B2↔B5, B3↔B4`); the other three quarters are symmetric ops. **4 profiles** each
  (Attack / Defense / Buildup / Pressure); pairing set by goal-relative position
  (attacking half → Attack vs Defense; own half → Buildup vs Pressure).
- **Class-clean S27 buckets** — each of the 29 attrs used once per contest (no
  double-count); the Skill battle uses **pure base buckets**, NOT the S27 role
  ratings (those blend Physical/IQ as a bonus → would double-count).
- **Two-stage resolution:** a battle = opposed micro-duels in **approach → main**;
  per-duel **Bradley-Terry** on weighted attribute scores; stage = weighted mean of
  its duels; **`threat = main·(g + (1−g)·approach)`**, `g = approach_gate` (tunable;
  0 = pure multiplicative, `g>0` lifts even contests). **PlayStyle families** modestly
  multiply the attrs in the duels they touch (**×1.05 base / ×1.10 plus**) — this is
  where item-5's deferred attr-emphasis families finally land.
- Built: **`data/config/zone_battle.json`** (Central-L1 only, both contexts) +
  **`src/load/v2_ingest/zone_battle.py`** (the 1v1 core). Validated on real players:
  **Kane vs Van Dijk** box threat **0.388** (Kane edges finish/movement, VVD wins the
  physical shake-off — faithful); **Van Dijk building vs Kane pressing 0.527** (plays
  out comfortably). Tuned: **`approach_gate = 0.5`** (even ≈ 0.375, range ~0.2–0.6);
  buildup `lane_space` **positioning → vision/composure** (EA `positioning` is
  *attacking* positioning — wrong for a CB receiving; surfaced by real data).

### S35 openers
1. **Author the other 8 zones** in `zone_battle.json` — template proven, config-only,
   no new code. Suggest **Wing-L1** next (byline/cross is most different from central).
   Each its own short discussion.
2. **Wire occupancy-weighted aggregation** — `zone_battle` is 1v1 so far; sum over all
   players present in a zone (item-6 boards), occupancy-weighted → per-zone team contest.
3. **THEN item 8** — value-weight each zone threat by `zone_xt` + possession-blend the
   two directional contests → team xG/xScoreline → sim. Carry the **offside gate** +
   **transition term** (both banked in `chessboard_design.md`).
4. Middle-third (L3) contest-pairing ambiguity; GK track (build-up distribution starts
   with the GK); set-piece overlay; calibrate weights / `g` / family-mult vs StatsBomb.

### Files (S34, uncommitted until the commit below)
- New: `docs/item7_zone_battle.md`, `data/config/zone_battle.json`,
  `src/load/v2_ingest/zone_battle.py`.
- Modified: `src/load/v2_ingest/kernel_transforms.py` (phase-grids refactor),
  `src/load/v2_ingest/formation_assembly.py` (item-6 synthesis), `docs/session_state.md`.
- **No DDL** — `db_schema.md` unchanged at 41 tables.

### S34 commit
```
S34: chessboard items 6 & 7 — synthesis boards + zone battle (Central-L1)

Item 6 (synthesis): formation_assembly now outputs two phase-separated per-zone
team boards (attack + defence); possession blend deferred to item-8 aggregation
(contests are directional). Refactored kernel_transforms -> transform_phase_grids()
returns per-phase grids (budget-normalised); transform_kernel() is now a thin
possession-blend convenience. team_boards() inverts per-slot grids into
zone -> [(slot, weight)]; per-slot grids stay the source of truth.

Item 7 (zone battle, framework + Central-L1): docs/item7_zone_battle.md. 9 zones
(3 lane x 3 goal-relative band-level, mirror-folded), 4 profiles each, class-clean
S27 buckets (each attr used once -> no double-count). Two-stage approach->main,
per-duel Bradley-Terry, weighted stages, threat = main*(g+(1-g)*approach); EA
PlayStyle families modestly multiply touched duel attrs (item-5 attr-emphasis lands
here). zone_battle.json (Central-L1) + zone_battle.py (1v1 core). Validated on
Kane vs Van Dijk (box 0.388) and Van Dijk-build vs Kane-press (0.527). Tuned
approach_gate=0.5; buildup positioning->vision/composure (EA positioning is
attacking-positioning, wrong for a CB receiving).

New:  docs/item7_zone_battle.md, data/config/zone_battle.json,
      src/load/v2_ingest/zone_battle.py
Modified: src/load/v2_ingest/kernel_transforms.py, src/load/v2_ingest/formation_assembly.py,
          docs/session_state.md
(No DDL -- db_schema.md unchanged at 41 tables.)

Refs: docs/item7_zone_battle.md, docs/session_state.md, docs/chessboard_design.md
```

## S33 outcome — chessboard items 4 & 5 built (transforms, assembly, Movement tweak)

Implementation session, shell-relay throughout (rule 12). Built the **SHIFT + TWEAK**
legs of the occupancy spine as **lazy pure functions** (decision B — no tables, fired
at formation-assembly time). All validated end-to-end via read-only probes.

### Item 4 — playstyle-axis → kernel transforms (DONE)
Design: `docs/item4_kernel_transforms.md`. `transform_kernel()` in
`src/load/v2_ingest/kernel_transforms.py` warps a code's two `occupancy_base` phase
kernels by a team's 5 blended axes:
- **possession** = phase blend `p·attack+(1−p)·defence` (outermost op)
- **line_height** = band translate (both phases)
- **press (ppda)** = forward push of the **defence kernel only**, weighted by empirical
  `forwardness(code)` (min-max of defence-phase centroid band; FW 1.0 → CB 0.0). CB=0
  ⇒ press never moves the back line. **Compression EMERGES** from line+press (no
  separate term, locked S33).
- **width** = lateral lane stretch ∝ `(lane−2)`; resolves LM/RM (narrow tucks them to
  the half-space; wide clips at touchline).
- **directness** = battle-layer (item 8), no static effect.
Mechanics: **bilinear splat** (smooth, mass-conserving) + edge-clip + renormalise.
Gains LOCKED S33 (`kernel_transforms.json`, env-overridable): **LINE 2.0, PRESS 2.0,
WIDTH 1.0** (±20 m line/press, ±16 m width at axis extremes). Validated: ESP CB
blended centroid matched the hand-prediction **exactly (2.041)**; URU press pushes ST
up; POR (wide) vs ESP (narrow) winger split clean.

### Formation assembly + lateral-fan (DONE)
`formation_assembly.py` — reuses the legacy `formations`/`formation_slots` (10
formations, slot→`position_code`). `assemble(formation, nation, [xi])` loops slots →
item-4 transform per slot. **Lateral-fan:** N>1 of a CENTRAL code (lane-2:
GK,CB,DF,DM,MF,CM,CAM,ST,FW) → symmetric lane offset (`FAN_STEP=1.0` → ±0.5, folded
into the single resample). GK parked. Validated: ESP 4-2-3-1 double `DM` → lanes
**1.500 / 2.500**; URU 3-5-2 front-two `ST` → 1.544 / 2.456 (slight inset = expected
edge-clip).

### Item 5 — player PlayStyle TWEAK (Movement leg DONE; attr-emphasis → item 7)
Split into two parts:
- **(a) tag→family map** = `data/config/playstyle_families.json` (36 tags → 5 families
  + GK/set-piece carve-outs), validated live by `validate_playstyle_families.py`
  (**PASS 36/36**; movement 4, finishing 6, passing 7, dribbling 3, defending 8, gk 6,
  set_piece 2).
- **(b) effects split by kind:**
  - **Movement** (Rapid, Quick Step, Relentless, Press Proven) = kernel tweak → **BUILT**.
    Rapid/Quick Step = forward band **SHIFT of the attack kernel** (a translate, not a
    forward tail — they stay maximally advanced). Press Proven = forward shift of the
    **defence** kernel (personal high-press, additive on team press). Relentless =
    **spread** (dilation about the per-phase base centroid) **+ availability boost**
    (budget rises >1: base 1.10 / plus 1.15 — "more available"; team intentionally NOT
    renormalised). base/plus magnitudes in `kernel_transforms.json` `movement_tweak`.
    Multiple tags **add**.
  - **Finishing / Passing / Dribbling / Defending** = attr emphasis → **DEFERRED to
    item 7** (they compound the zone-attribute matrix; nothing to modulate until it exists).
Integration: `assemble()` gained optional `xi={slot_no: ea_id}` (no XI = neutral, the
default); the player tweak folds into `transform_kernel`'s **single** resample.
Validated with `--demo` (real movers): stacking works (a Relentless+/Rapid/Quick Step
DM → band up + **sum 115%**); every unfilled slot byte-identical to neutral.

### Banked for item 8 (design notes, in `chessboard_design.md`)
- **Offside = relational threat-gate, NOT an occupancy clip.** Enter ONCE at the
  contest (gate *threat*, not presence) → no double-count (empirical occupancy is
  already onside-realistic). **Offside line = REARMOST outfield defender** (2nd-last
  opponent), read off the deepest CB's **occupancy distribution** → **probabilistic**
  gate; NOT the `line_height` mean (dragged forward by pressers). `line_height` enters
  only via where item 4 puts the CB kernel. Pace (Rapid/Quick Step "danger-zone nudge",
  banked item 5) modulates the gate.
- (S32-carried) transition/turnover value (56% of open-play goals) = battle-layer term,
  not in static xT.

### S34 openers
1. **Item 6 — synthesis.** Largely already done: `formation_assembly` composes
   BASE⊕SHIFT⊕TWEAK. May only need the **tier/output shape** (home/primary/secondary/
   tertiary slicing of the final kernel) + a clean return contract for items 7/8.
2. **Item 7 — attribute→zone relevance matrix** (D7). The deferred 4 attr-emphasis
   families land here, compounding the team-generic `(lane-type × band × phase)` matrix.
   Consumes `player_adjusted_attributes_wide`.
3. **THEN design item 8** — battle resolution + xScoreline, carrying the offside gate +
   transition term banked above.
4. v2 banked: item-4 per-phase line treatment + possession→share remap curve; width
   StatsBomb calibration; Quick Step lateral-separation component; pace↔press tradeoff;
   spread-narrowing under extreme press.

### Files (S33, uncommitted until the commit below)
- New: `docs/item4_kernel_transforms.md`, `docs/item5_movement_tweak.md`,
  `data/config/kernel_transforms.json`, `data/config/playstyle_families.json`,
  `src/load/v2_ingest/kernel_transforms.py`, `src/load/v2_ingest/formation_assembly.py`,
  `src/load/v2_ingest/validate_playstyle_families.py`.
- Updated: `docs/chessboard_design.md` (item-8 offside finding), `docs/session_state.md`.
- **No DDL** — decision B adds no tables; `db_schema.md` unchanged at 41.

### S33 commit
```
S33: chessboard items 4 & 5 — kernel transforms, formation assembly, Movement tweak

Built the SHIFT + TWEAK legs of the occupancy spine as lazy pure functions
(decision B; no tables, fired at assembly time).

Item 4 (kernel_transforms.py + data/config/kernel_transforms.json): transform_kernel
warps occupancy_base phase kernels by team_playstyle_blended axes -- possession
phase-blend, line band-translate, press forward-push of the defence kernel
(forwardness-weighted, CB=0 so the back line is untouched; compression emergent),
width lane-stretch. Bilinear splat + renorm. Gains LINE/PRESS/WIDTH = 2/2/1.

Formation assembly (formation_assembly.py): reuses formations/formation_slots;
item-4 transform per slot + lateral-fan for duplicated central codes (FAN_STEP 1.0,
folded into one resample); GK parked.

Item 5 (playstyle_families.json + validate_playstyle_families.py): 36 EA PlayStyles
-> 5 families + GK/set-piece, validated live (PASS 36/36). Movement leg built into
transform_kernel (Rapid/Quick Step forward attack shift; Press Proven forward defence
shift; Relentless spread + availability boost >1) + optional xi wired into assembly.
Finishing/Passing/Dribbling/Defending deferred to item 7.

Offside banked for item 8 (chessboard_design.md): relational threat-gate off the
rearmost defender's occupancy distribution, not the line_height mean; no occupancy
clip / no double-count; pace modulates.

New:  docs/item4_kernel_transforms.md, docs/item5_movement_tweak.md,
      data/config/{kernel_transforms,playstyle_families}.json,
      src/load/v2_ingest/{kernel_transforms,formation_assembly,validate_playstyle_families}.py
Updated: docs/chessboard_design.md, docs/session_state.md
(No DDL -- db_schema.md unchanged at 41 tables.)

Refs: docs/item4_kernel_transforms.md, docs/item5_movement_tweak.md, docs/chessboard_design.md
```

## S32 outcome — D2 team playstyle FINISHED (nation map + prior/blend)

Shell-relay throughout (rule 12). Completed the D2 leg: bridged the S31 empirical
table to the 48 nations, then designed + built + applied the prior+blend.
Design docs: **`docs/d2_nation_map.md`**, **`docs/d2_prior_blend_design.md`**.

### Built — `derive_team_playstyle_blended.py` → `team_playstyle_blended` (DB 38→39)
One row per **WC2026 nation (48)**, 5 axes blended `(1−λ_team)·prior + λ_team·
empirical`, self-contained on FIFA-3 (no FK exposure). `--apply` = CREATE OR
REPLACE. Stores blended axes + `lambda_team` + the prior + the empirical combine
+ `has_empirical`/`prior_source` for full audit. Verified: Spain poss 0.835/line
0.888, Germany line 0.842/poss 0.852, Portugal wide 0.673 vs Spain narrow 0.212,
Uruguay press 0.862 (Bielsa) — reads like scouting profiles.

### The model (full detail in d2_prior_blend_design.md)
- **Nation map:** SB team string → FIFA-3 via `nation_codes.json` + 3-entry
  `statsbomb_team_aliases.json` (Cape Verde Islands/Congo DR/Côte d'Ivoire).
  71 SB teams → 39 qualifiers map, 32 non-qualifiers drop, **9 nations dark**
  (Bosnia, Curaçao, Haiti, Iraq, Jordan, NZ, Norway, Sweden, Uzbekistan).
  Verified 39/32/9 against the live 96-row table. Kept all 96 rows / no re-norm.
- **λ_team** = `λ_max·(1−exp(−Σe/τ))`; `e_r = recency × volume × continuity` per
  (nation,tournament) row, same currency combines the rows AND sets trust.
  recency: 2024=1.0, WC22=ρ. volume `m/(m+m₀)`. continuity from
  `coach_continuity.json` (1.0 same coach, 0.5 changed — gathered S32 from a
  dated June-2026 source; 59 qualifier rows, 24 same / 35 changed).
- **Prior = confederation mean** (empirical-Bayes shrinkage; `confederations.json`,
  80 nations incl. non-qualifiers in the pool). Only NZ (sole OFC) → global mean.
  Dark sides = pure prior (λ=0). Formalises the "non-qualifier sides as proxies"
  idea from d2_nation_map.md.
- **Tuning (S32 sweep, `_probe_blend_sweep.py`):** less shrinkage chosen so
  tournament identity expresses. **Locked S2b: `ρ=0.8, m₀=3, λ_max=0.9, τ=0.4`**
  (env-overridable). Elites λ≈0.80–0.86, thin/coach-changed ≈0.35, dark 0;
  higher τ separates well-covered from thin rather than a uniform lift.

### Files (S32, uncommitted)
- New: `docs/d2_nation_map.md`, `docs/d2_prior_blend_design.md`,
  `data/config/statsbomb_team_aliases.json`, `data/config/coach_continuity.json`,
  `data/config/confederations.json`,
  `src/load/v2_ingest/derive_team_playstyle_blended.py`,
  `src/load/v2_ingest/_probe_blend_sweep.py` (**deletable**).
- Updated: `docs/db_schema.md` (39 tables), `docs/session_state.md`.

### Chessboard item 1 — zone grid + xT — DONE (S32)
- `data/config/zone_grid.json`: 6 bands × 5 lanes = 30 zones, 120×80 pitch,
  attack-orientation. `derive_zone_xt.py` → `zone_xt` (30 rows; DB 39→40).
- **Empirical Markov xT** estimated natively from StatsBomb intl events (NOT
  Karun-collapsed; viability verified — per-origin outflow min 1,382). Turnover
  absorbing state is **load-bearing** (without it m≈1, no contraction, flat
  surface — caught + fixed S32). **L/R reflection-symmetric by construction**
  (reflection augmentation; default on, `--asymmetric` to compare) — the value
  matrix is symmetric *a priori*, removing footedness/small-sample/skilled-player
  asymmetry. Surface: peak B6-C 0.143, monotonic toward goal. Tiny banked cleanup:
  value iteration hits the 100-iter cap (slow geom rate, stable to <1e-4) — report
  residual + raise default iters next touch.
- **Item-8 finding banked** (`docs/chessboard_design.md`): 56% of open-play goals
  are turnover-sparked; regain zones anti-correlated (−0.61) with clean xT →
  transition value belongs in the battle layer, not the static surface.

### Chessboard item 2 — position → home anchor — DONE (S32)
- `data/config/position_home_cells.json`: 23 `position_code`s → **continuous home
  anchor `(band_pos, lane_pos)`** (integers = cell centre, **.5 = edge**), keyed on
  the `positions` table (vocab verified 23/23). Lane from `flank`; central
  flanked codes (LCB/RCB, LCM/RCM, LAM/RAM) → half-spaces, wide codes → wings.
  Clean spine GK→CB→DM→CM→CAM→ST. Edge anchors: ST/FW B5/B6 (4.5), CAM B4/B5
  (3.5), LWB/RWB B3/B4 (2.5).
- **Item-3 rule banked** (`chessboard_design.md`): N>1 of a central code →
  **fan laterally** at assembly (2×ST → B5/B6 × C/half-space corners; 2×DM/CM →
  C/LHS & C/RHS edges). Formation property, kept out of the static map.

### Chessboard item 3 — base occupancy kernels — DONE (S32)
- `derive_occupancy_base.py` + `data/config/occupancy_events.json` →
  **`occupancy_base`** (533 rows; DB 40→41). Per `(position_code, phase)` a
  30-zone occupancy kernel, presence budget 1.0, tiered (home/primary/secondary/
  tertiary). **Empirical, derived straight from StatsBomb** (NOT hand role
  templates — those banked as v2 prior): **attack phase = on-ball events,
  defence phase = defensive actions** — so D5's two-kernel split is *measured*,
  and the attack→defence shift is role-specific (CB shifts ~4 bands deep+central,
  ST ~0). Mirror-symmetrised (L↔R exact, `symmetry check 0.0`), set-pieces
  excluded (open play only), truncated at 3% then renormalised → 6–19 cells/kernel.
  22 codes (GK separate track). Validated: LCB attack B2-3 LHS vs defence B1-C;
  LW attack B5-LW vs defence tracks to B2-4; DM symmetric pivot.
- **Big consequence:** item 4's *empirical leg is already banked* — the two phase
  kernels exist; item 4 is now just the playstyle *transforms* that warp them.

### S33 openers
1. **Code chessboard items 4–7** (opener #3, items 1–3 DONE) — config-driven:
   **(4) playstyle-axis → kernel transforms** (next — the SHIFT leg, D5: possession
   = phase blend `p·attack+(1−p)·defence` of `occupancy_base`; line height =
   vertical translate; width = lateral stretch + wing/half-space bias, resolves
   LM/RM; press = forward-shift defence kernel; directness mostly battle tempo).
   Then **(5) PlayStyle→family map**, **(6) attribute-relevance matrix** [+ tier
   semantics]. Plus the **lateral-fan rule** (N>1 central code) at formation
   assembly. Consumes `occupancy_base` + `team_playstyle_blended` +
   `player_adjusted_attributes_wide` + `zone_xt`.
2. THEN design **item 8 — battle resolution** (carry the S32 transition finding:
   transition/turnover value is a battle-layer term, not in static xT).
3. v2 banked (D2): per-axis λ_max; τ calibration; leave-one-out confederation
   prior; non-qualifier-as-proxy hand priors; externalise blend tunables to a
   `d2_blend_params.json`; coach-continuity as graded not binary.

### S32 commit (run after review)
```
S32: D2 team playstyle finished — nation map + confederation-prior blend

Bridged team_playstyle_empirical (S31) to the 48 WC2026 nations and built the
prior+blend -> team_playstyle_blended (48 nations x 5 axes; DB 39 tables).
Nation map = nation_codes + 3 SB aliases (71 SB teams -> 39 qualifiers, 9 dark).
lambda_team = lambda_max*(1-exp(-sum_e/tau)); e_r = recency x volume x continuity
(coach_continuity.json, gathered from a dated 2026 source). Prior = confederation
mean (confederations.json; empirical-Bayes shrinkage). Tuned via _probe_blend_
sweep.py; locked S2b (rho=0.8, m0=3, lambda_max=0.9, tau=0.4) for tournament
identity over shrinkage. Env-overridable tunables; blend math in one reusable fn.

New:  docs/d2_nation_map.md, docs/d2_prior_blend_design.md,
      data/config/{statsbomb_team_aliases,coach_continuity,confederations}.json,
      src/load/v2_ingest/derive_team_playstyle_blended.py,
      src/load/v2_ingest/_probe_blend_sweep.py (deletable)
Updated: docs/session_state.md, docs/db_schema.md (39 tables)

Refs: docs/d2_prior_blend_design.md, docs/d2_nation_map.md, docs/chessboard_design.md
```

## S31 outcome — team-playstyle EMPIRICAL leg built (D2 implementation begins)

First implementation-phase session after the S30 chessboard design. Built the
empirical leg of **D2 team playstyle** from StatsBomb events. Shell-relay
throughout (rule 12). Full design + citations: **`docs/playstyle_empirical_design.md`**
(new).

### Built — `derive_team_playstyle_empirical.py` + `data/config/playstyle_metrics.json`
DERIVED table **`team_playstyle_empirical`** (NEW → DB **38 tables**): one row per
`(team, competition_id, season_id)` = **96 team-tournament rows** across the 4 SB
intl tournaments (WC22 32 / Euro24 24 / Copa24 16 / AFCON23 24). Five axes, each
stored **raw + percentile-rank normalised** across the 96-row pool (1 = high end).
Config-driven (tunables in JSON: tournaments, zone lines, channel bounds, action
sets). `--apply` = CTAS wholesale rebuild; self-contained on SB IDs → no FK
exposure. Applied + verified.

### Five metrics (observe-driven; design-doc has detail + citations)
1. **Directness** — median pass distance + share-forward (`end_x>x`), combined
   post-norm.
2. **Width** — wing-channel (`y≤18 or y≥62`) share of pass+carry starts,
   **attacking half only (`x≥60`)**. Refined S31: all-pitch version was
   buildup-diluted (≈inverse possession); attacking-half isolates *attacking*
   width and cleanly splits Portugal (wide) from Spain (narrow) at equal possession.
3. **Line height** — **median x of BACK-LINE players' (`position LIKE '%Back%'`)
   defensive engagements**. Calls: mean dragged low by deep Clearances/Blocks
   (excluded); all-player median measures *press* not line (forwards press high,
   10–17u inflation, team-dependent) → isolate defenders; mode-of-5m-bins rejected
   (broad plateaus → unstable) for median.
4. **Press = PPDA** (pinned + cited: Hudl/StatsBomb + Premier League) — opp
   completed passes (`outcome IS NULL`) in own 60% (`x≤72`) ÷ team def-actions in
   attacking 60% (`x≥48`); def set = Interception/Foul/Block/Dribbled Past +
   **tackle-only Duels** (`raw.duel.type.name='Tackle'`; Duel is ~50% aerials).
   Norm inverted (1 = most intense press).
5. **Possession** — team pass-share in its matches.

### Coordinate convention CONFIRMED (not assumed, rule 3)
StatsBomb normalises every event to the acting team attacking +x; **no halftime
flip**. Verified three ways: period split (Georgia P1 39 / P2 44 — a flip implies
39/81), per-match stability, same-match check. → per-team `x` valid as-is.

### Validation (reputation + independent recompute)
Directness: patient sides floor (Germany .02, Italy .05, Portugal .07, Spain .16),
direct sides top (Namibia .98, Mauritania .96). Line: Canada/Brazil/England/Spain/
Germany highest. Press: Algeria, Mexico, Mali, **Bielsa's Uruguay 5.39**.
**Internal consistency:** Spain near-identical across WC22 & Euro24; **Morocco
possession .11 (WC22 low-block) vs .78 (AFCON dominant)** — vindicates the
`(team,tournament)` grain + recency plan. Independent from-scratch recompute of
Spain@Euro24 matched persisted exactly (line 49.00, poss 0.5815).

### S32 openers
1. **StatsBomb team → 2026 nation map** — join `team_playstyle_empirical` to the
   WC2026 nations (FIFA-3). Not all SB teams are 2026 qualifiers; dark AFC/Gulf
   set has no SB data → pure prior.
2. **D2 prior leg + blend** — hand-assign the 5-axis current-2026 prior
   (concentrate on no-data sides); `axis = (1−λ_team)·prior + λ_team·empirical`,
   `λ_team` = intl coverage recency-weighted (2024 ≻ WC22); coach-change flag.
3. Then **code chessboard items 1–7**, THEN design **item 8 (battle resolution)**.
4. v2 banked: width final-third cross-check; **game-state weighting** on line
   height (Spain 69→57 H1→H2 protecting leads); secondary press-height signal
   (MID_FWD engagement-x); completed-vs-all pass for possession; CB-only line purity.

### Files (S31, uncommitted)
- New: `docs/playstyle_empirical_design.md`,
  `src/load/v2_ingest/derive_team_playstyle_empirical.py`,
  `data/config/playstyle_metrics.json`.
- Updated: `docs/db_schema.md` (38 tables), `docs/session_state.md`.

### S31 commit
```
S31: team-playstyle empirical leg -> team_playstyle_empirical (D2 implementation)

First chessboard-implementation session. Built the empirical leg of D2 team
playstyle from StatsBomb intl events: derive_team_playstyle_empirical.py +
data/config/playstyle_metrics.json -> team_playstyle_empirical (96 team-tournament
rows, 4 tournaments). Five axes (directness, width, line height, PPDA, possession),
each raw + percentile-rank normalised across the pool. Width restricted to
attacking half; line height = median x of back-line defensive engagements only;
PPDA pinned + cited (tackle-only Duels). Coordinate normalisation confirmed
empirically. Validated vs reputation + independent recompute.

New:  docs/playstyle_empirical_design.md
      src/load/v2_ingest/derive_team_playstyle_empirical.py
      data/config/playstyle_metrics.json
Updated: docs/session_state.md, docs/db_schema.md (38 tables)

Refs: docs/playstyle_empirical_design.md, docs/chessboard_design.md, docs/session_state.md
```

## S30 outcome — chessboard (stage 2) design, end to end (battle math deferred)

Pure brainstorm/design session. Canonical artifact: **`docs/chessboard_design.md`**
(read it for full detail; summary below). Model: `(formation + team playstyle + 11
adjusted-attribute vectors)` per team → zone-by-zone battles → team xScoreline →
sim. Governing rule: parameterised tactical **prior, not a black box**, validated vs
StatsBomb spatial truth. **Spine** = per-player graded zone occupancy:
`final tiered zones = BASE(formation) ⊕ SHIFT(team playstyle) ⊕ TWEAK(player playstyle)`.

### Decisions locked (all in chessboard_design.md)
- **D1 Geometry:** **6 bands × 5 lanes = 30 zones**, reflection-symmetric
  (orientable per team), xT-valued (collapse Karun-Singh 16×12 onto 30). P2 = 6×4
  kept as a complexity-ablation fallback. Lanes LW·LH·C·RH·RW; bands B1 own-box →
  B6 opp-box.
- **D2 Team playstyle:** 5 continuous axes (directness, width, line height, press,
  possession) + archetype presets. **Hybrid sourcing** (same shape as EA↔empirical
  blend): empirical from StatsBomb intl events (pass length, lateral share,
  def-action height, PPDA, possession%) ⊕ hand prior (mainly the no-data dark set),
  coverage+recency weighted; coach-turnover caveat.
- **D3 Base occupancy:** home cell per code on the real 23-code vocab. LCB/RCB home
  = half-space; CAM central; FB→B3/WB→B4/winger→B5. LM/RM + ST flagged
  context-dependent (resolved by SHIFT/TWEAK).
- **D4 Occupancy = role spread kernels + tier semantics:** presence budget = 1.0;
  each cell weight does double duty (occupancy share × attribute scalar). Occupancy
  = role kernel (4 dials: fwd/back/lateral reach + spread), normalised; tiers =
  weight bands (~5–10 cells; box-to-box wide, CB tight). ~6 role templates.
  **Open-play only**; set-pieces deferred overlay.
- **D5 Playstyle → kernel transforms:** each role has attack + defence kernels.
  Possession = phase blend `p·attack+(1−p)·defence`; line = vertical translation
  (both); width = lateral stretch + wide-player lane bias (resolves LM/RM); press =
  forward-shift of the **defence kernel only**; directness = mostly battle tempo.
- **D6 Player PlayStyle families (data-validated):** 36 EA tags → 5 outfield
  families (Movement=kernel tweak; Finishing/Passing/Dribbling/Defending=attr
  emphasis) + GK (parked) + Set-piece (deferred). Modal-by-position analysis
  confirmed family→role attachment. Effects modest; never re-inflate adjusted
  attribute values.
- **D7 Attribute→zone relevance:** team-generic matrix, ~6 `(lane-type × band-role)`
  archetypes → attacking vs defending attribute sets (of the 29). Numeric weights
  deferred to tuning-on-data. GK interfaces at the box archetype.

### S31 openers — IMPLEMENTATION phase (battle math comes AFTER)
1. **Load/observe sample data** to ground the build: StatsBomb intl events for D2
   empirical style metrics + occupancy/touch validation.
2. **Code items 1–7** incrementally (config-driven, `data/config/` pattern): zone
   grid + xT collapse; position→home-cell map; role kernels; playstyle-axis
   transforms; PlayStyle→family map; attribute-relevance matrix.
3. **THEN design item 8 — battle resolution** (1v1 vs aggregate zone contest →
   per-zone xThreat → team xG → scoreline; bivariate-Poisson precedent from md38)
   with real numbers in hand. Then StatsBomb spatial validation; Streamlit.
4. Carried v2: dark-player attribute fallback; StatsBomb per-match stats + clutch +
   recency; soft/dual group membership; tighten `invert_pct`.

### S30 commit (design-only; no code/DB)
```
S30: chessboard (stage 2) design — geometry, playstyle, occupancy/kernels, relevance

Full stage-2 tactical-model design on paper (docs/chessboard_design.md, D1-D7):
6x5 xT-valued board; 5-axis team playstyle w/ hybrid StatsBomb+prior sourcing;
per-player graded occupancy via role spread kernels (budget=1, tier=weight bands);
playstyle axes as kernel transforms; 36 EA PlayStyles -> 5 data-validated families;
attribute->zone relevance matrix. Battle resolution (item 8) deferred to after
loading sample data + coding items 1-7.

New:  docs/chessboard_design.md
Updated: docs/session_state.md

Refs: docs/chessboard_design.md, docs/analysis_pipeline_design.md, docs/session_state.md
```

## S29 outcome — adjusted attributes persisted to a real table

Build session; design (table shape) was settled first. Shell-relay throughout.

### Decision — long table + materialised wide (LOCKED)
`player_adjusted_attributes` **long** (grain `(squad_row_id, attribute)`, PK), one
row per player×attribute with full provenance: `ea_raw, shift_s, adj, adj_pct,
lambda_dim, bucket, is_discriminator, position_group, model_version, created_at`.
Chose long for auditability ("why is his finishing 96?" answerable from one row) +
extensibility; maintainer's standing preference for normalised large data.
- **`adj` stored CONTINUOUS** (DOUBLE), not rounded to EA ints — round at display.
- **All 29 attrs stored** (bonus at raw EA, shift_s=0) so the row is self-contained
  (no re-join to `ea_fc26_player` to reassemble a player).
- **Wide = materialised TABLE** `player_adjusted_attributes_wide` (PIVOT … USING
  max(adj)), NOT a view: DuckDB PIVOT has dynamic columns, unreliable in
  CREATE VIEW; CTAS is safe and rebuilt alongside the long table → no drift.

### Built — `derive_adjusted_attributes.py` (new, PERMANENT)
Promotes the S28 prototype logic into a DERIVED deriver. `eng.build()` reused
(invert_pct **inlined** so this permanent file doesn't depend on the deletable
`_probe_adjusted_attributes.py`). `--apply` = wholesale CREATE OR REPLACE rebuild
(idempotent; self-contained grain → no FK-block exposure). Dry-run computes + prints,
writes nothing. **Applied + verified:** 21228 rows / 732 players; numbers match the
prototype exactly (Van Dijk Def s=−9.76→adj 81.2, Attack s=0 off-role gate; Salah
Att s=+1.64→fin 95.6, Def s=0; bonus buckets all 0). Wide spot-check: pace/athletic
carried at raw EA alongside form-adjusted output attrs. `db_schema.md` → 37 tables.
- **v1 scope:** EA-present players only (`ea_id NOT NULL`); GKs excluded (separate
  track, dropped in build()); dark-player position-average fallback deferred.

### Plumbing — `_probe_adjusted_ratings.build()` now carries the PK
`build()` SELECT + rows now include `squad_row_id` + `ea_id` (clean PK joins
downstream, kills a name_norm fan-out risk). `_probe_adjusted_attributes.py`
simplified to merge EA attrs straight on build's `ea_id`. (Naming debt noted:
`_probe_adjusted_ratings.py` is the PERMANENT engine despite the `_probe_` prefix —
rename someday.)

### S30 openers
1. **Chessboard (stage 2)** — start `analysis_pipeline_design.md` stage 2: pitch
   zone grid (xT) + formation→zone occupancy + playstyle modifiers, consuming
   `player_adjusted_attributes_wide`. Likely a fresh design doc.
2. Streamlit dashboard (player radars off the wide table + coverage indicator).
3. v2 carried: dark-player fallback; StatsBomb per-match stats + clutch + recency;
   soft/dual group membership (Bruno/Bellingham); tighten `invert_pct`
   (np.percentile vs pandas-rank); cross-source identity unification.

### Owed housekeeping (carried from S28)
- Soften "~100% EA baseline" in `analysis_pipeline_design.md` (815/1247 = 65%).
- `validate_v104_ingest.py` for UEL/UECL + UCL 25-26.
- Delete spent probes (S20–27 list). Keep permanent S27/S28/S29 files.

### S29 commit
```
S29: persist adjusted attributes -> player_adjusted_attributes (long) + _wide (pivot)

Promote the S28 form->sub-attribute mapping into a DERIVED table the chessboard
consumes. Long grain (squad_row_id, attribute) with full provenance (ea_raw,
shift_s, adj, adj_pct, lambda_dim); adj stored continuous; all 29 attrs/player
(bonus at raw EA). Wide = materialised PIVOT table (CTAS; view unreliable for
dynamic PIVOT columns). 21228 rows / 732 EA-present outfield players; verified vs
prototype. build() now threads squad_row_id/ea_id for clean PK joins.

New:  src/load/v2_ingest/derive_adjusted_attributes.py
Modified: src/load/v2_ingest/_probe_adjusted_ratings.py (PK threaded through build),
          src/load/v2_ingest/_probe_adjusted_attributes.py (merge simplified)
Updated: docs/session_state.md, docs/db_schema.md (37 tables)

Refs: docs/blend_redesign.md, docs/session_state.md
```

## S28 outcome — blend re-tune + form→sub-attribute mapping (design + prototype)

Design-led session on top of the S27-cont engine. All read-only; full reasoning
in **`docs/blend_redesign.md`** (new). Shell-relay throughout (rule 12).

### Decision 1+2 — λ reframed as confidence; CAPs re-tuned (LOCKED)
- λ's per-dim CAP **reframed** from "minutes ceiling" to **per-dimension
  confidence** (signal reliability). Blend kept **symmetric** — asymmetry rejected
  because it bakes in "trust EA about elites" (the bias we calibrate away), and a
  low CAP already **self-bounds** the max swing to `CAP·100`.
- CAP **Attack .80→.60 / Possession .80→.50 / Defense .50→.25** (overridable via
  `CAP_ATT/CAP_POSS/CAP_DEF` env). The ordering *encodes* the data-reliability
  ranking (Understat xG best → most empirical weight; cups counting-stat proxy
  worst → least). Van Dijk Defense **69→85** (fair). Side effect: tempers the
  young-overperformer spikes (Ouedraogo Att 83→67).

### Attribute mapping — discriminators-only uniform shift (LOCKED)
Chessboard consumes *individual attributes* (verified in `analysis_pipeline_design.md`
zone-battles), so a dimension's form pct maps down onto sub-attributes:
`adj_rating_d = invert(adj_pct_d, group EA-rating dist)` → `δ = adj_rating − raw` →
`s_d = δ/BASE_W` (=δ/0.75) applied **uniformly to the discriminator attrs only**
(ATTACK/POSSESSION/DEFENSE lists in `_ea_attribute_buckets`); bonus buckets
(Skills/IQ/**Physical** incl. pace) untouched. Rationale: signal is
dimension-aggregate (no within-dim info → uniform is the only honest shape); form
is output not athleticism; base attrs are role-exclusive (no shared-attr conflict).
`s=δ/0.75` **confirmed by observation** (Van Dijk role −7.3 → s −9.8 → attrs −10;
the discriminators-only choice amplifies attr move 1.33× vs dim move). No clips hit.

### Off-role gate — Option A (LOCKED, prototype-driven)
Prototype surfaced the **biggest** shifts on *off-role* dims (CB Attack −13 to
shot_power from set-piece-noise goals+xa; playmaker Defense −13 from noisy cup
tackles). CAP is global-per-dim, blind to (dim×group) signal quality. Fix:
**λ→0 for off-role dims**. `RELEVANT = {DEF:{Poss,Def}, MID:{Att,Poss,Def},
FWD:{Att,Poss}}` (MID = pivots/box-to-box; CAMs/wingers are FWD). Verified:
Rüdiger Attack + De Bruyne Defense now `s=+0.0`, attrs untouched; on-role unchanged.

### Grouping audited (maintainer doubt re De Bruyne) — clean
Watchlist dump of `squad_position_profile` minutes vs assigned group: every
assignment matches minutes-dominant group. **De Bruyne→FWD correct by his own
data** (3074 min FWD-coded CAM vs 1055 MID), not just the rule. Only near-coin-
flips: Bruno Fernandes (FWD 4291/MID 3105) + Bellingham (MID 4044/FWD 3267) — land
correctly on dominant side; banked **v2 idea: soft/dual group membership** for true
hybrids (hard buckets judge them vs one peer set only). Not fixed now.

### Files (S28, uncommitted)
- **New:** `docs/blend_redesign.md`, `src/load/v2_ingest/_probe_adjusted_attributes.py`
  (the form→attribute mapper; deletable probe).
- **Modified:** `src/load/v2_ingest/_probe_adjusted_ratings.py` — env-var CAPs +
  new locked defaults; refactored into `build()`/`report()`/`main()` so other
  probes reuse the blend (DRY); added `RELEVANT` off-role gate.

### S29 openers
1. **Persist adjusted attributes to a real (non-probe) table** — promote the
   mapping out of `_probe_adjusted_attributes.py` into a proper deriver writing
   per-player adjusted sub-attributes (the chessboard's input). Decide table shape
   (long `(squad_row_id, attribute, ea_raw, adj)` vs wide) + idempotent rebuild.
2. Then **chessboard** (stage 2) + Streamlit dashboard.
3. v2 layer: StatsBomb per-match stats + clutch + recency; soft group membership;
   cross-source identity unification; tighten `invert_pct` (np.percentile vs
   pandas-rank convention — small approximation noted in the prototype).

### Owed housekeeping (carried)
- **Soften "~100% EA baseline"** in `analysis_pipeline_design.md` (measured 815/1247 = 65%).
- `validate_v104_ingest.py` for UEL/UECL + UCL 25-26.
- Delete spent probes (S20–27): `_probe_coverage_audit.py`,
  `_probe_coverage_statsbomb.py`, `_probe_resolver_overlap.py`, the S27 validation
  probes, etc. (Keep the four permanent S27 files + the two S28 ones for now.)

### S28 commit
```
S28: blend re-tune (confidence CAPs) + form->sub-attribute mapping (discriminators, Option A gate)

Reframed lambda as per-dimension confidence; kept the blend symmetric (low CAP
self-bounds the swing). CAPs Attack .60 / Possession .50 / Defense .25 (encodes
data-reliability ordering); Van Dijk defence 69->85. Designed + prototyped the
form->attribute mapping: a dimension's blended percentile maps down onto its EA
discriminator sub-attributes via a uniform additive shift (s = delta/0.75),
bonus/Physical/IQ left at EA. Off-role gate (Option A): off-role dims stay pure
EA prior (DEF no Attack, FWD no Defence). Grouping audited clean.

New:  docs/blend_redesign.md
      src/load/v2_ingest/_probe_adjusted_attributes.py  (deletable)
Modified: src/load/v2_ingest/_probe_adjusted_ratings.py (env CAPs + new defaults,
          refactor build/report/main, RELEVANT off-role gate)
Updated: docs/session_state.md

Refs: docs/blend_redesign.md, docs/session_state.md
```

## S27 outcome — coverage reconciliation + coverage/prior design spine + StatsBomb minutes

Three threads: reconcile all gathered data into a coverage picture, design the
coverage/EA-calibration/prior-shrinkage spine, build the per-90 prerequisite.

### Coverage reconciliation (`_probe_coverage_audit.py`, new, deletable)
Per-player + per-nation coverage across the 4 sources. Name-based detection
(cross-source identity gap: `our_player_id` reaches FBref cups but NOT Understat
— disjoint id spaces; unifying identities deferred to attribute-synthesis).
- Per-source (of 1247): EA 815 (65%), top5 504 (40%), cups 528 (42%), intl 287
  (23%); **any-source 920 (74%), dark 327 (26%)**. Sources/player: 0→327, 1→256,
  2→258, 3→262, 4→144.
- Defensive-action coverage 625 (50%); position skew **mild** (cups patch
  defenders); GK = special case (own track).
- **KEY data-shape finding:** attacking well-served (Understat xG); defensive/
  duel/dribble is a CLUB-football hole (Understat none; cups only tackles/int,
  no xG; StatsBomb intl-only) → **EA carries the defensive load**, and the real
  free-data gap is defensive depth, not dark rosters (the true paid argument,
  parked).

### Design spine — `docs/coverage_prior_design.md` (new, no model code yet)
- **ONE per-player operation** (not group-calibrate-then-shrink): EA is a stale,
  biased prior; pull each player toward THEIR OWN recent empirical percentile,
  weighted by coverage λ. Empirical used once → no double-count. Group/league
  de-bias demoted to optional v2 (only helps dark players).
- Three empirical components, ALL **per-90, position-relative percentiles**:
  attacking/buildup (top5 25-26≻24-25≻Euro24/Copa24≻AFCON23; WC22 excluded—too
  old), defensive (UCL/UEL/UECL + intl tackles/int/duels), clutch (high-stakes
  attack vs league baseline (+), fouls/cards (−); WC22 attack feeds clutch; no
  positive defensive clutch). Recency = source weights, not a separate decay.
- Blend: `attr_dim = (1−λ)·EA_pct + λ·empirical_pct + clutch`; dark → position-avg.
- Coverage λ = weighted noisy-OR (top5 1.0>intl0.85>EA0.5>cups0.4); two numbers
  (coverage_total dashboard, coverage_empirical=λ). Dimension-aware = v2.

### Built — StatsBomb minutes (`derive_statsbomb_minutes.py`)
- → `statsbomb_player_match` (6201 player-matches / 199 mt / 1717 players).
  minutes from Starting XI + Substitution + red/2nd-yellow caps; match_end =
  max(minute) over periods 1–4 (**period 5 = shootout, excluded** — fixed a
  24-row >130 inflation). Validated: GER-SCO exact (Porteous 41', full 93, HT
  subs 45/48); **0 team-matches not-starting-11**; ET caps 126.
- DERIVED table → `--apply` rebuilds wholesale (CREATE OR REPLACE), safe.
- `db_schema.md` regenerated (34 base tables).

### S28 openers
1. **StatsBomb per-match stat aggregation** (goals/shots/tackles/int/duels/
   dribbles/fouls/cards from events → per-player-match) — next prerequisite; the
   minutes now exist to per-90 it.
2. **Per-90 percentile pipeline** (§3.1–3.3) across all 3 empirical sources →
   position-relative attacking/defensive percentiles + clutch.
3. Coverage λ computed + persisted (per-player + per-nation table).
4. Per-player blend → attribute estimates. Open: clutch form/cap (D-blend-2);
   tune weights/recency/saturation.

### Owed housekeeping (carried)
- **Soften "~100% EA baseline"** in `analysis_pipeline_design.md` — measured
  EA reaches **815/1247 = 65%**.
- `validate_v104_ingest.py` for UEL/UECL + UCL 25-26.
- Delete spent probes: `_probe_coverage_audit.py` + `_probe_coverage_statsbomb.py`
  (coverage banked), `_probe_resolver_overlap.py`, older S20–24 probes.

### S27 commit
```
S27: coverage reconciliation + coverage/prior design spine + StatsBomb minutes

Per-player + per-nation coverage audit across all 4 sources (name-based;
cross-source identity gap surfaced). Banked the data-shape finding (defensive
is the club hole; EA carries defence). Designed the coverage/EA-calibration/
prior-shrinkage spine (one per-player blend toward own empirical percentile,
per-90 position-relative; 3 components attacking/defensive/clutch; recency via
source weights). Built StatsBomb minutes deriver -> statsbomb_player_match
(6201 rows; period-5 shootout excluded; validated GER-SCO).

New:  docs/coverage_prior_design.md
      src/load/v2_ingest/_probe_coverage_audit.py  (deletable)
      src/load/v2_ingest/derive_statsbomb_minutes.py
Updated: docs/session_state.md, docs/db_schema.md (34 tables)

Refs: docs/coverage_prior_design.md, docs/session_state.md
```

## S27 (cont.) — per-dimension adjusted-rating engine built

Big modeling session on top of the S27 commit. Full as-built model in
`docs/coverage_prior_design.md` §8. GKs are a SEPARATE track, excluded from this
engine (Attack/Possession/Defense are outfield only).

### Position groups (applied)
- `_position_groups.py` (3 source vocabs → coarse) + `derive_position_groups.py`.
  Understat `AMR/AML` (wingers) → FWD; `CAM/AMC` → FWD (maintainer: MID = the
  pivot, not attacking mids). GK guard. Persisted
  `wc2026_squad.primary_position_group` (DEF 399/FWD 371/MID 332/GK 145) +
  `squad_position_profile` (per-source appearance counts). 71 MID→FWD vs Wiki.

### EA decomposition (`_ea_attribute_buckets.py`)
- 3 role buckets (Attack/Possession/Defense, clean discriminators) + 3 bonus
  buckets (Skills/IQ/Physical) applied with role-weights (3/2/1 matrix);
  `role = 0.75·base + 0.25·weighted_bonus`. heading_accuracy→Attack (= scoring).
  Validated: Haaland top Attack, De Bruyne top Possession, Van Dijk top Defense.

### Empirical per-90 percentiles (within position group, club v1)
- Attack = (goals+xa)/90 [Understat only]; Possession =
  (key_passes+xg_buildup+xg_chain)/90 [Understat]; Defense = 0.6·padj + 0.4·
  suppression [FBref cups]. padj = possession-adjusted tackles+int (rescues
  dominant-team CBs from the volume trap); suppression = inv(opp SoT+goals
  conceded). Caught + banked: raw tackles+int badly misranks elite CBs.

### The blend (`_probe_adjusted_ratings.py` — the engine)
- `adj = (1−λ)·EA_role_pct + λ·emp_pct`; λ = min(min/900,1)·CAP;
  CAP {Attack .8, Possession .8, Defense .5}. Reads like real scouting profiles.

### Known residuals (v2 todo)
- Small-sample young overperformers spike (need stronger minutes-shrinkage).
- Elite CBs dinged on defense (Van Dijk 100→69) — λ_def is the dial; counting
  stats can't capture solidity.
- StatsBomb per-match stats + clutch + recency NOT yet folded in.
- Cross-source identity unification still deferred.

### S28 openers (maintainer steer, S27 close)
1. **Re-tune the defense blend — it adjusts too strongly.** Van Dijk 100→69 is
   too harsh given the empirical defensive signal is the *unreliable* one.
   Lower λ_def and/or a smarter blend (e.g. resist pulling a high-EA player
   DOWN when empirical confidence is low; asymmetric / confidence-weighted).
2. **Design the empirical→EA adjustment framework properly** — how the
   empirical percentile should move the EA rating **per bucket**
   (Attack/Possession/Defense each may warrant different strength/shape), and
   how the three then combine into an **overall** rating. This is the next
   real design conversation (supersedes the flat per-dimension λ caps).
3. Then: StatsBomb per-match stats + clutch + recency (v2), persist ratings.

### Deletable validation probes
`_probe_position_groups.py`, `_probe_ea_role_ratings.py`,
`_probe_empirical_percentiles.py`, `_probe_coverage_audit.py`,
`_probe_coverage_statsbomb.py`. (`_probe_adjusted_ea_v1.py` deleted — superseded
by `_probe_adjusted_ratings.py`.) Permanent: `_position_groups.py`,
`derive_position_groups.py`, `_ea_attribute_buckets.py`,
`_probe_adjusted_ratings.py` (the engine).

## S26 outcome — StatsBomb ×3 loaded; coverage re-measured; resolver built + applied

Shell-relay throughout (rule 12). Three threads: finish StatsBomb acquisition,
re-measure coverage, design+build the resolver.

### StatsBomb acquisition complete (all 4 tournaments)
- Loaded WC22 (43/106), Copa24 (223/282), AFCON23 (1267/107) via the same
  `ingest_statsbomb.py` (one `--tournament` change each). NoAuthWarning
  silenced (cosmetic edit). Sidecar totals: **199 matches / 685788 events /
  5,783,812 frames / 1718 distinct StatsBomb players; orphans 0.**
- **360 reality (observed, contradicts the catalog flag):** WC22 + Euro24 =
  full 360; Copa24 = none (catalog-correct); **AFCON23 advertises
  `match_available_360` but effectively HAS none** (1 event, 13 frame rows).
  → usable spatial-validation set = **WC22 + Euro24 only**. Copa no-360
  degradation branch verified (frames=0, no crash).

### Coverage re-measured — `_probe_coverage_statsbomb.py` (new, deletable)
- **Baseline drift resolved:** S24's "365 dark" was a mid-load snapshot; both
  the old and new probe now agree on **351** at the full `players`=7537.
  (Owed: the "365" mention upthread in S24 is superseded by 351.)
- StatsBomb's net dark-rescue is only **29** (strict name+nation) → truly
  dark 322 / overall 925 (74.2%) on a loose name basis.
- **KEY finding (banked):** the dark set is **largely genuine absence**, not a
  matching artifact — concentrated in **AFC/Gulf** (Jordan, Uzbekistan, Iraq,
  Qatar, Iran). Their tournament, **AFC Asian Cup 2023, is NOT in StatsBomb
  open data** (verified absent from the 80-row catalog) and has no free xG.
  Evidence: Jordan 0/26 in all four tournaments (Jordan is AFC, not in AFCON);
  Qatar 3/26 (in WC22 but real roster turnover WC22→2026). Fuzzy recovers
  ~nothing here. → **resolves the parked PAID gate: only a paid Asian-coverage
  feed lights up the dark set; free path structurally can't.**

### Resolver — designed (D1–D5) + built + applied
- `docs/resolver_design.md` (new) + `resolve_squad_links.py` (new). Fills
  `wc2026_squad.ea_id` (**815**) + `our_player_id` (**528**), idempotent
  `UPDATE ... FROM`. Coverage: both=472, ea_only=343, emp_only=56, **dark=376**
  (corroborated — stricter/honester than the 351 loose-name count).
- Model: candidate-by-`name_norm` → year+nation disambiguation ladders →
  discrete-tier confidence (0.95 `exact+nation+year`, 0.85 `exact+nation`).
  Nation MISMATCH → reject ("better dark than wrong"). EA nation alias overlay
  (Holland→NED, Korea Republic→KOR…); **QAT genuinely absent from EA** (not an
  alias gap).
- **D1 REVISED on dry-run evidence:** guarded fuzzy mis-merged same-nation
  same-age names — `mohamed alaa→salah` (EGY), `kim jin/min gyu`,
  `kim tae/dae hyeon` (KOR) all passed nation+age. Fix: **strengthened
  `name_norm` (strip ALL non-alphanumerics)** so punctuation/spacing/diacritic
  variants (`son heung-min`==`son heung min`) become EXACT; **dropped generic
  fuzzy** (gated `--fuzzy`, off). Net: same-quality coverage, zero false
  positives, all-exact.
- Minor open: `exact` accept-low = 0 (no unique-Understat-only matches) —
  plausible, worth a later glance.

### S27 openers (clean)
1. **Coverage score (item c) + EA-empirical blend/shrinkage** — now unblocked:
   `ea_id` (prior) + `our_player_id` (empirical) + per-link confidence all
   exist. This is the next modelling decision (deferred in `data_sourcing.md`).
2. Then chessboard (stage 2) + Streamlit dashboard.
3. Optional/deferred: StatsBomb player xref (D2), club alias map (D5),
   `--fuzzy` revisit with token-aware matching, accept-low=0 glance.

### Owed housekeeping (surface, schedule)
- **Soften "~100% EA attribute baseline"** in `analysis_pipeline_design.md` —
  now have the hard number: EA corroborated-reaches **815/1247 = 65%**.
- `validate_v104_ingest.py` for UEL/UECL + UCL 25-26 (S24 owed).
- Delete spent probes: `_probe_coverage_statsbomb.py` (after coverage banked —
  it is, here), `_probe_resolver_overlap.py`, `_probe_uel_uecl_schedules.py`,
  `_probe_wc2026_squads.py`, `_probe_nation_codes.py`.
- No `db_schema.md` regen needed (no DDL this session).

### S26 commit
```
S26: StatsBomb ×3 loaded; coverage re-measured; squad resolver built + applied

Loaded WC22/Copa24/AFCON23 into the sidecar (all 4 tournaments now: 199 mt /
685788 ev / 5.78M frames / 1718 intl players; orphans 0). Observed AFCON23
360 effectively absent despite catalog flag; usable 360 = WC22+Euro24.

Coverage re-measured: dark set is largely genuine absence (AFC/Gulf squads;
AFC Asian Cup 2023 not in free data) -> resolves paid gate.

Resolver (resolve_squad_links.py + docs/resolver_design.md): fills
wc2026_squad.ea_id (815) + our_player_id (528); name_norm hardened, fuzzy
gated off after it mis-merged same-nation same-age names.

New:  docs/resolver_design.md
      src/load/v2_ingest/resolve_squad_links.py
      src/load/v2_ingest/_probe_coverage_statsbomb.py  (deletable)
Updated: src/load/v2_ingest/ingest_statsbomb.py (NoAuthWarning silence),
         docs/session_state.md

Refs: docs/resolver_design.md, docs/statsbomb_ingest_design.md, docs/session_state.md
```

## S25 outcome — StatsBomb Open sidecar designed + Euro 2024 loaded

Design-led session, then the build. Shell-relay throughout (rule 12).
Full design in `docs/statsbomb_ingest_design.md` (D1–D3b, all observe-driven).

### Observed (verified S25 via `sb.competitions()`, not inferred)
- `statsbombpy` 1.19.0 added via `uv add` (→ `pyproject.toml` + `uv.lock`
  changed). Open-data tier emits a benign `NoAuthWarning` per call.
- The four targets by **composite `(competition_id, season_id)`** (season_id
  is NOT unique alone — Euro24 & Copa24 both 282): **WC22 (43,106) +360 ·
  Euro24 (55,282) +360 · Copa24 (223,282) NO 360 · AFCON23 (1267,107) +360.**
- `sb.frames()` df path is broken (`InvalidIndexError`) → always use
  `fmt='dict'`. Events `fmt='dict'` = lossless nested (the `raw` source).
  Full-360 frames are anonymized (no player_id); per-shot `shot_freeze_frame`
  is named + lives inside `statsbomb_event.raw`.

### Built (all applied + verified)
- **`migrate_statsbomb_schema.py`** — 4 NEW sidecar tables, additive,
  idempotent. Dry-run **compiles every DDL in-memory** (rule 4) before apply;
  native `JSON` type confirmed on this build; `index`→`event_index` (reserved).
  Self-contained on StatsBomb's ID space → **zero links into players/games**,
  no FK-block exposure. No declared FKs inside the sidecar (app-enforced,
  mirrors `wc2026_squad.our_player_id`).
- **`ingest_statsbomb.py --tournament {wc2022,euro2024,copa2024,afcon2023}`**
  (`--apply`/`--limit`). Per-match `INSERT OR IGNORE` (bounded memory),
  hybrid typed-cols + `raw` JSON built from one `fmt='dict'` pass.
- **Euro 2024 loaded:** `statsbomb_match` 51 · `statsbomb_event` 187924 ·
  `statsbomb_frame` 2698999 · `statsbomb_frame_meta` 164530 · 1340 shots
  w/ xG · 495 distinct StatsBomb player_ids · comp/season `(55,282)`.
  **Orphan checks 0** (frame→event, event→match). `json_extract` round-trip
  on `raw` confirmed (top xG goals render correctly). Idempotent re-run safe.
- DB base tables 29 → **33** (+`statsbomb_match/event/frame/frame_meta`).

### S26 openers (clean)
1. **Load the other 3 tournaments** — same loader, just `--tournament wc2022`
   / `copa2024` / `afcon2023` (copa2024 has NO 360 → frame tables stay empty
   for it, by design). Each ~similar scale; WC22 is the big one.
2. **Re-measure coverage** — re-run `_probe_resolver_overlap.py`; StatsBomb's
   495 intl players (×4 tournaments) should shrink the 247-strong dark set.
3. **Then the resolver** (`statsbomb_player_id`/`wc2026_squad` xref), then
   coverage score, then EA-empirical blend. Dashboard still S26+ (Streamlit).

### Owed housekeeping (surface, schedule when convenient)
- Regenerate `docs/db_schema.md` (now DUE — 4 new tables); included in the
  S25 commit block below.
- Add a `validate_v104_ingest.py`-style section (or a small
  `validate_statsbomb.py`) for the sidecar — the orphan/count checks ran
  inline this session but aren't yet a committed validator.
- Still owed from S24: `validate_v104_ingest.py` for UEL/UECL + UCL 25-26;
  soften "~100% EA attribute baseline" in `analysis_pipeline_design.md`;
  delete spent probes (`_probe_resolver_overlap.py` — keep until coverage
  re-measure, `_probe_uel_uecl_schedules.py`, `_probe_wc2026_squads.py`,
  `_probe_nation_codes.py`).
- Cosmetic: silence `NoAuthWarning` in `ingest_statsbomb.py` (snippet noted
  in S25 chat) next time the file is touched.

### S25 commit (run after regenerating db_schema.md)
```
S25: StatsBomb Open sidecar — design + Euro 2024 loaded (event + 360)

New self-contained sidecar (own ID space, zero links into players/games):
statsbomb_match/event/frame/frame_meta. Raw events stored (typed cols +
raw JSON), aggregation deferred downstream. Euro 2024 fully loaded:
51 matches / 187924 events / 2.7M frame rows / 1340 shots w/ xG; orphans 0.

New:  docs/statsbomb_ingest_design.md
      src/load/v2_ingest/migrate_statsbomb_schema.py
      src/load/v2_ingest/ingest_statsbomb.py
Updated: docs/session_state.md, docs/db_schema.md (33 tables),
         pyproject.toml + uv.lock (statsbombpy 1.19.0)

Refs: docs/statsbomb_ingest_design.md, docs/session_state.md
```

## S24 outcome — UEL + UECL loaded; resolver overlap measured (then parked)

Continued the data-acquisition track (sequencing: gather → THEN coverage →
THEN resolver/blend). Shell-relay workflow throughout (rule 12).

### Loaded — UEFA Europa League + Conference League, both seasons
- Overlay extended: `data/config/league_dict.json` +`UEFA-Europa League`
  (FBref `"UEFA Europa League"`) +`UEFA-Conference League` (FBref
  `"UEFA Conference League"` — NOT "Europa Conference", verified vs cached
  catalog). Re-ran `setup_soccerdata_overlay.py` (3 entries now).
- Probe `_probe_uel_uecl_schedules.py` confirmed columns identical to UCL →
  `ingest_fbref.py` reused with **zero code changes**.
- Fetched both leagues in **parallel** (2 background dry-runs, read-only →
  coexist; ~2h wall), then **4 applies sequentially** (game_id minting reads
  committed max, so sequential = collision-free; ids now 10000378–10001061).
  Applied: UEL 24-25 (189g/5851pm/911pl), UEL 25-26 (189/5899/921), UECL
  24-25 (153/4718/880), UECL 25-26 (153/4736/889). All guards passed; UECL
  lost 7 pm rows to PK INSERT-OR-IGNORE dedup (benign).
- Totals: FBref games 1062 (378 UCL + 378 UEL + 306 UECL). `players` 4880→
  **7537**, with_dob 1415→**4070 (54%)**. db_schema.md regenerated (29 tables).

### Resolver overlap measured — then PARKED (premature until StatsBomb)
`_probe_resolver_overlap.py` (uncommitted, S24) sized squad↔EA / squad↔players
match BEFORE the StatsBomb load. Key finding (banked, revisit post-StatsBomb):
- **EA is NOT a ~100% baseline** — only 68% (850/1247) of squad players match
  EA by exact name; ~247 genuinely absent, concentrated in **whole dark
  squads** (Qatar 26, Jordan 25, Iran 25, Uzbekistan 24, S.Africa/Egypt 21…)
  — Gulf/Asian/African domestic leagues EA + our club data both miss.
- Coverage matrix (exact name_norm): both=536, EA-only=314, empirical-only=32,
  **neither(dark)=365**. EA ambiguity trivial (9, split by club+age).
  Empirical: 568 any, 277 dob-confirmed, 244 name-only ambiguous.
- **Owed doc fix:** soften the "~100% attribute baseline" claim in
  `analysis_pipeline_design.md` (the locked *philosophy* holds; the number is
  wrong). StatsBomb (intl tournaments) is expected to materially shrink the
  dark set — that's WHY resolver/coverage waits for it.

### S25 openers
1. **StatsBomb Open ingest** (`ingest_statsbomb.py`, statsbombpy) — event +
   360 for WC22/Euro24/Copa24/AFCON23. New sidecar schema. The real new build.
2. Then re-measure coverage (re-run `_probe_resolver_overlap.py`), THEN build
   the resolver (`wc2026_squad.ea_id` + `our_player_id`), THEN coverage score.
3. Housekeeping: `validate_v104_ingest.py` for UEL/UECL + UCL 25-26; delete
   probes; commit S24.

## S23 outcome — dashboard/analysis track opened; UCL 25-26 + squad + EA loaded

Design + build session. Shell was unavailable to the assistant the whole
session (WSL UNC mount error) → **new workflow (Claude.md rule 12): assistant
hands copy-paste bash blocks, Indraneel runs them + pastes output.** Worked
well. Read-only DB reads + dry-runs done concurrently with the live fetch.

### Data loaded (all applied + verified)
- **UCL 2025-26** via `ingest_fbref.py --season 2025-2026 --apply` (dry-run
  cached first, ~off-cache apply). 189 games / 378 team_match_fbref / 5850
  player_match_fbref. Player resolver: 341 reused + 537 newly minted, 0
  rough-merges. `players` now **4880** (was 4343), **with_dob 1415** (was 878).
  ⚠️ owed: `validate_v104_ingest.py` Section 10 not re-run for 25-26 (apply's
  inline guards passed: 378==2×189, score xcheck, FK orphans 0).
- **`wc2026_squad`** (new table) via `ingest_wc2026_squads.py --apply`:
  1247 players / 48 nations / 48 captains. Idempotent re-run = 0 inserts
  (natural-key UNIQUE confirmed; nextval PK confirmed).
- **`ea_fc26_player`** (16228 men) + **`ea_fc26_playstyle`** (15032) via
  `ingest_ea_fc26.py --apply`. INSERT BY NAME + float→int coercion confirmed.
- `db_schema.md` regenerated → **29 tables**.

### New files (S23, uncommitted)
- `docs/analysis_pipeline_design.md` (spine; S22-close), `docs/data_sourcing.md`
  (items a + b fully designed), `data/config/nation_codes.json` (48 WC nations
  → FIFA-3, validated).
- `src/load/v2_ingest/ingest_wc2026_squads.py`, `ingest_ea_fc26.py`.
- `src/load/v2_ingest/_probe_wc2026_squads.py`, `_probe_nation_codes.py`
  (probes — **now deletable**).
- `notebooks/explore_worldcup.ipynb` (DB explorer, read-only short-lived conns),
  `notebooks/explore_ea_fc26.ipynb` (EA CSV explorer).
- EA Kaggle CSVs under `data/raw/eafc26/` (flynn28 = anchor; talha = backup).
- Claude.md: rule 11 (S20-22 trial) **sunset**; rule 12 (shell-relay) added.

### Key decisions banked (don't relitigate)
- Squad source = **Wikipedia** "2026 FIFA World Cup squads" (only free source
  with the full link key name+nation+dob+club in one parse; 48×~26=1247).
- Nations parse from `<h3>` (groups are `<h2>`); accept a wikitable only if
  cols == the 7-field squad schema (drops summary tables). DoB needs dateutil
  (page mixes 'May 17, 2000' US + '8 October 1997' intl formats).
- Matching model = **candidate-by-`name_norm`, then disambiguate by what each
  candidate carries** (dob for FBref subset / club-alias+league for Understat
  subset). Our `players` is thin (id,name,dob); 80% dob-NULL + Understat has
  NO nation. Club too noisy → tiebreaker only.
- EA anchor = **flynn28 EAFC26.csv** (has PlayStyles + GK + OVR; talha lacks
  them). Filter GENDER='M'. 6 family scores `ea_`-prefixed (collide with sub
  -attrs). PlayStyle tiers = base/plus only (no ++). EA nation spellings differ
  ('Holland','Korea Republic') → reconcile in resolver, nation_code NULL for now.
- **Sequencing (agreed):** gather data → decide paid → THEN coverage (item c)
  → THEN EA-empirical blend/shrinkage. Don't fit coverage to a moving footprint.

### S24 openers (clean)
1. **EA↔squad / squad↔players resolver** — fill `wc2026_squad.ea_id` +
   `our_player_id` + `link_method`/`link_confidence`. Needs EA-nation alias
   (Holland→NED…) + club alias map. The first real coverage signal.
2. Then continue data acquisition (international-first: WCQ/friendlies/NL/
   continental; UEL/UECL; StatsBomb Open) — scoped by the squad roster.
3. Coverage score (item c) + EA-empirical blend — AFTER acquisition.
4. Housekeeping owed: `validate_v104_ingest.py` for UCL 25-26; delete probes;
   **commit S22 + S23** (S22 still unpushed: origin/main=c9b4ff0, HEAD=c6f69b3).

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S21 start, HEAD was `5e7ecdd S20: Path A probes —
  FBref overlay confirmed for CL; routine dep refresh` (clean tree).
- S21 close commit (intended): see "Commit message" below.
- **Out-of-repo state worth knowing:**
  `~/soccerdata/config/league_dict.json` overlay was rewritten this
  session — now matches the in-repo `data/config/league_dict.json`
  (UCL entry only, no WhoScored line, no unverified extras). `.bak` of
  S20-era version preserved adjacent.
- `~/soccerdata/data/FBref/` has substantial cache from this session:
  189 cached match HTMLs (`match_<id>.html`) for UCL 2024-25 plus
  matchlogs for 36 teams in schedule + shooting stat_types. ~10–20 MB
  on disk. Useful for any S22 re-probe — cache hits are instant.
- Verify before trusting: `git log --oneline -5` and
  `git status --short`. (Observe, don't infer.)

## S21 outcome — Path A confirmed; xG industry-shift discovered; free-only strategy chosen

### What we set out to do (per S20 close-out)

S21 step 1 (commit overlay + setup script), step 2 (probe FBref
team/player match shapes for UCL), step 3 (schema delta design),
step 5 (schema migration), step 6 (build `ingest_fbref.py`).

### What we actually did

Steps 1 + 2 only — step 2 took us much deeper than planned because we
discovered a real-world industry shift.

#### ✅ Step 1: overlay committed + setup script

- `data/config/league_dict.json` — in-repo canonical overlay,
  UCL only, no unverified WhoScored line.
- `src/tools/setup_soccerdata_overlay.py` — merges in-repo → user
  config, in-repo wins on conflict, `.bak` backup, idempotent. Verified
  via running and observing diff output (existing user file had a
  WhoScored line; backup made; correct merge).

#### ✅ Step 2 Phase 2b/2c probes done

Three probes; deletable in S22+ once `ingest_fbref.py` lands and the
design doc captures all findings (it does already):

- `src/load/v2_ingest/_probe_UCL_team_player_shapes.py` —
  `read_team_match_stats(stat_type='schedule')`. **1,121 rows** (vs
  ~378 expected for UCL alone): `all_comps` URL hardcoded in
  soccerdata returns each team's matches across every competition.
  `league` index = `<NA>`.
- `src/load/v2_ingest/_probe_UCL_team_player_extended.py` —
  `read_team_match_stats(stat_type='shooting')` + `read_player_match_stats(stat_type='summary')`.
  Step 1 (~6 min wall): same contamination, no xG. Step 2 (~70 min
  wall, vs 22-min estimate): 5,826 rows, 189 games, 878 distinct
  players, league correctly `'UEFA-Champions League'`. No xG.
- soccerdata source-read: `_parse_table` (`fbref.py:1037–1064`) does
  no column filtering; just runs `pd.read_html`. So if Expected
  subgroup is missing, FBref didn't serve it.

#### 🚨 xG investigation — root cause is industry-wide

Both probes returned **no Expected subgroup / no xG**. Three rounds
of diagnostics confirmed FBref's HTML doesn't carry xG-related
`data-stat` values for UCL anymore (137 comments in match HTML are
all short navigation remnants, no hidden xG tables).

Web search revealed the cause: **Jan 20, 2026 — Sports Reference lost
their data partnership with Opta/StatsPerform.** All advanced stats
removed from FBref output industry-wide (xG, npxG, xAG, progressive
passes, shot-creating actions, expected-goals-against). Banked
permanently in `Claude.md` + `docs/v104_ingest_competitions.md`.

Refs:
- https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/
- https://ricardoheredia.substack.com/p/farewell-fbref-advanced-stats-when

#### Track B research (alternative xG sources)

Investigation confirmed there is no single-source free replacement
for FBref's advanced stats. Findings:

- **StatsBomb Open Data** (free, event-level + 360 spatial): excellent
  for **WC 2022, Euro 2024, Copa 2024, AFCON 2023**. **NOT** for
  current UCL (latest = 2018/19), Europa League (only 1988/89),
  Conference, qualifiers, friendlies, Nations League, current
  domestic seasons. Useful as a separate S23+ track for the major
  intl tournaments we'd want xG on.
- **fotmob-api** (free unofficial library): last release Feb 2024,
  v1.0.0, 5 stars, 14 total commits, "ToDo!" documentation. ~24
  months stale vs FotMob's evolving anti-scraping. Almost certainly
  broken; skip unless we want to maintain ourselves.
- **api-football** (paid, ~$19/mo, RapidAPI): xG coverage is
  "inconsistent" per their own docs. Defer.
- **Sportmonks paid xG add-on / football-data.org paid tier**: defer.

User decision at S21 close: **free-only path; revisit paid only if
modeling actively needs xG for non-Understat/non-StatsBomb comps.**

#### xG coverage under free-only strategy (the honest matrix)

| Comp | xG source | xG available? |
|---|---|---|
| Top-5 domestic 2024-25, 2025-26 | Understat (already loaded) | ✅ |
| WC 2022 | StatsBomb (S23+) | ✅ event-level + 360 |
| Euro 2024 | StatsBomb (S23+) | ✅ event-level + 360 |
| Copa 2024 | StatsBomb (S23+) | ✅ event-level |
| AFCON 2023 | StatsBomb (S23+) | ✅ event-level + 360 |
| UCL, UEL, Conference 2024-25 / 2025-26 | FBref via soccerdata | ❌ no xG |
| AFCON 2025, Asian Cup 2024, Gold Cup 2025 | FBref via soccerdata | ❌ no xG |
| WC Qualifiers 2026 (6 confeds) | FBref via soccerdata | ❌ no xG |
| UEFA Nations League | FBref via soccerdata | ❌ no xG |
| International friendlies | FBref via soccerdata | ❌ no xG |

Modeling implication: where we have xG (top-5 domestic + 4 intl
tournaments), use it. Elsewhere, lean on goals + shots + form +
lineups + formations + round + venue. Documented gap, not a bug.

### What we banked in Claude.md

- Jan 2026 FBref/Opta termination + xG sourcing implications.
- soccerdata's `read_team_match_stats` all-comps contamination.
- soccerdata's `_parse_table` is just `pd.read_html` — doesn't filter
  columns; missing columns mean FBref didn't serve them.
- 22-min estimate vs 70-min observed wall-time for one UCL season of
  per-match player stats. Capacity-planning fact.
- In-repo overlay + setup-script pattern.

## S22 outcome — schema delta design LOCKED (step 3 complete)

Design-only session, no code, no live DB writes. All eight schema
deltas decided one-at-a-time; deliverables written:
`docs/v104_ingest_competitions.md` "Schema deltas — RESOLVED S22 step
3" + new `docs/v104_schema_migration.md` (migration plan + DDL sketch).

**Governing architecture: Option C — source-separated FBref fact
tables.** FBref per-match data → new `team_match_fbref` /
`player_match_fbref`; Understat fact tables untouched; 3 shared
dimensions (`games`, `players`, `positions`) take additive changes
only; cross-source via union views. Migration is **pure additive**
(ADD COLUMN / INSERT / CREATE) — sidesteps every DuckDB FK-block gotcha.

Decisions (detail in the two docs):
- (a) `game_id` stays INTEGER + surrogate (≥10M) for FBref + new
  `source`/`source_game_id` — **pushed back on VARCHAR recreate**.
- (b) `games.stage` + `games.venue` (VARCHAR NULL; `stage` not `round`
  — ROUND() clash).
- (c) score → `home_goals/away_goals/home_pens/away_pens` on `games`,
  parsed loader-side; validator cross-check. Understat backfill
  deferred to one post-gather shot.
- (d) multi-pos: source-aware `_position_policy.py` + coarse
  `DF/MF/FW` codes in `positions`; primary-token wins.
- (e) age → `players.player_dob` (back-computed, validated).
- (f) MultiIndex flatten helper + curated `FBREF_COL_MAP`
  anti-corruption layer, **fail loud on unmapped**.
- (g) all-comps filter **inverted**: `read_schedule` game_id
  membership = primary; URL-slug + round enum = fail-loud secondary.
- (h) Option C source-separated tables (above).

**⚠️ Shell was unavailable this whole session** (UNC mount error — bash
could not start). State was verified via the pasted
`validate_v104_ingest.py` output only: 9/10 Understat confirmed, DB
grand totals identical to the 2026-06-05 `db_schema.md` dump (→ DB
untouched since S21). **Still NOT verified (owed next session):**
`git log`/`git status` (HEAD `c9b4ff0`? 5 ahead? clean tree?), and
whether the soccerdata package / `league_dict.json` overlay moved.
These are **pre-flight gate 1** in `v104_schema_migration.md` and must
pass before any migration statement runs.

## S22 implementation — UCL 2024-25 loaded end-to-end (steps 4–8 done)

Pre-flight gates all passed (git HEAD c9b4ff0 confirmed — note: repo was
already pushed, origin/main == HEAD, NOT 5-ahead as prior state said;
DB untouched; observe-probes run). Then, observing-before-coding, two
design-doc premises were corrected against real data (S14 lesson):

- **Score shootout format is `(N) R–R (N)`** (e.g. `(1) 0–1 (4)` = reg
  0–1, pens 1–4), NOT the doc's guessed `1 (4)`. Also `team_match`
  GF/GA carry the same parens (`'1 (2)'`) — parse leading int.
- **Player-match `pos` is a MIX**: granular (CB/LB/DM…, already in our
  vocab) + coarse (DF/MF/FW) + multi (`DF,MF`) + `AM` (= our CAM). The
  doc's "all coarse `DF,MF`" was the season-pos, not match-pos.

New empirical findings banked:
- **FBref `read_player_match_stats` exposes player NAME, no numeric id.**
  → mint surrogate player_ids (base 50_000_000).
- **Player dob drifts ±1–2 days across a player's matches** (FBref age
  rounding). So the surrogate key is `(norm_name, nation)`, with a
  **canonical dob = modal derived dob** stored on `players`. Keying on
  exact dob over-split 878 players into 1163 — caught in dry-run.
- **`team_match` exposes no game_id** → parse 8-char hash from
  `match_report` URL; filter by membership in the clean `read_schedule`
  set (decision g primary).
- **`position_id` is Understat-native** (a source column, not derived);
  FBref has none → `player_match_fbref.position_id` left NULL, link via
  `effective_position` → `positions.position_code`. Vestigial column;
  drop in a later cleanup migration if desired.
- season comes back `'2425'` (mapped to `'2024-2025'`, reused Understat
  SEASON map).

Build status (active task step list):
1. ✅ Commit overlay + setup script (S21).
2. ✅ Probe team_match + player_match shapes for UCL (S21).
3. ✅ Schema delta design — LOCKED (S22).
4. ✅ **Migration applied** — `migrate_v104_fbref_schema.py` (additive,
   idempotent, dry-run/--apply). games +8 cols, players +player_dob,
   positions +DF/MF/FW, +team_match_fbref / player_match_fbref tables,
   +team_match_all / player_match_all views.
5. ✅ **`ingest_fbref.py` built** — Sections A (schedule→games) / B
   (team_match→team_match_fbref) / C (player_match→players +
   player_match_fbref). `_position_policy.py` extended source-aware
   (`fbref_effective_position`, AM→CAM, primary-token). Dry-run/--apply.
6. ✅ Dry-run UCL 2024-25 — eyeballed 189 / 378 / 5826, all guards pass.
7. ✅ **Live load UCL 2024-25** — 189 games, 378 team, 878 players,
   5826 player_match. Idempotent re-run confirmed (0 new).
8. ✅ **`validate_v104_ingest.py` extended** (Section 10, Option C) +
   run clean: invariant 378==2×189, score cross-check 0 mismatch, all
   FK orphans 0, dob 878/878.
9. ⬜ **Live load UCL 2025-26** — NEXT. NOT cached → ~70-min live
   rate-limited fetch (`read_player_match_stats`). Same command,
   `--season 2025-2026`. Run in a dedicated/background session.
10. ⬜ Then replicate the pattern for UEL/UECL/continentals/WCQ/friendlies.
5. **Build `ingest_fbref.py`** (S22).
6. **Dry-run UCL 2024-25** — eyeball ~189 games / ~378 team_match
   after filter / ~5,826 player_match rows.
7. **Live UCL 2024-25 load**.
8. **Re-run `validate_v104_ingest.py`** — expect 10/11 (10 Understat +
   1 UCL); still excluding GER 24-25 unless re-attempted.
9. **Live UCL 2025-26 load**.

Then S23+: replicate pattern for UEL, UECL, Continental, WCQ,
Friendlies. Open separate `ingest_statsbomb.py` track for event-
level WC/Euro/Copa/AFCON xG.

## Deferred

- **Commit S21 work** — see "Commit message" at end.
- **Commit S22 work** — docs (`v104_ingest_competitions.md` updated,
  `v104_schema_migration.md` new, this file) AND code
  (`migrate_v104_fbref_schema.py`, `ingest_fbref.py`,
  `_position_policy.py` FBref extension, `validate_v104_ingest.py`
  Section 10). NOTE: migration already APPLIED to the live DB; backups
  at `worldcup.duckdb.s22-bak` (pre-migration) and
  `worldcup.duckdb.s22-preload-bak` (post-migration, pre-FBref-load).
- **Understat `games` goals backfill** — populate
  `home_goals/away_goals` (+pens NULL) for the 3,198 existing rows from
  `team_match_stats`, in one shot once all sources are gathered
  (decision c).
- GER-Bundesliga 2024-25 (soccerdata upgrade exhausted at S20).
- **Probe files — now deletable** (`ingest_fbref.py` has landed):
  - `src/load/v2_ingest/_probe_UCL_team_player_shapes.py` (S21)
  - `src/load/v2_ingest/_probe_UCL_team_player_extended.py` (S21)
  - `src/load/v2_ingest/_probe_s22_schema_shapes.py` (S22)
  - `src/load/v2_ingest/_probe_s22_pos_coverage.py` (S22)
  - (S20-era probes too)
- **Regenerate `docs/db_schema.md` — now DUE** (migration applied +
  UCL loaded): `uv run python src/tools/dump_db_schema.py`.
- **`player_match_fbref.position_id`** — vestigial NULL column
  (Understat-only field); optional later cleanup-migration to drop it.
- `derived_state_freshness` table + `check_freshness.py` tool.
- Recompute `player_season_stats` for newly-loaded leagues.
- Re-run paid-API check (api-football, Sportmonks) if modeling needs
  xG for non-Understat / non-StatsBomb comps.
- StatsBomb Open Data ingest track (S23+).
- **S23 DASHBOARD + ANALYSIS track** — see new
  `docs/analysis_pipeline_design.md` (agreed S22-close): Streamlit
  dashboard (locked), pipeline = player Att/Mid/Def attributes → zonal
  "chessboard" battles (xT-grounded) + playstyle modifiers → team
  xScoreline → sim. Data: international-first (FBref WCQ/friendlies/
  intl) + StatsBomb Open (spatial validation) + **EA Sports FC 26 attrs
  via Kaggle CSV** (coverage solver / informative prior; NOT SoFIFA —
  Cloudflare-blocked) + optional cheap paid API. Per-player coverage =
  a feature + shrinkage weight. Full S23 pickup prompt in S22-close chat.

## Design decisions banked (don't relitigate)

From `docs/v104_ingest_design.md`:
1. INSERT OR IGNORE everywhere, no content-hash detection.
2. Append-only, no historical re-fetch.
3. One file per source, sectioned by table.
4. Explicit `derived_state_freshness` tracking, manual refresh control.
5. Incremental migration via `src/load/v2_ingest/`.

From S17 (`Claude.md`):
- Mixed-enforcement NOT NULL: DB-level on 5 of 7 league-bearing
  tables; app-code on `games` + `fixtures`.
- No outer transaction wraps multi-step DuckDB migrations.

From S18 (`docs/v104_ingest_understat.md`):
- Option C (passthrough + assertion) — does NOT apply for FBref
  team_match (S21: league is `<NA>`).
- `effective_position` policy at `_position_policy.py`; needs
  extension for FBref multi-position `'DF,MF'` shape (S22).
- New-league fallback (decision (a)): sub-only players land on `'Sub'`.
- `players` dimension maintenance inside Section B.

From S19:
- Validation script as the standard post-load eyeball.
- 9/10 coverage with one known gap is shippable.

From S20:
- soccerdata's `league_dict.json` overlay is canonical extension path.
- Default `available_leagues()` is curated subset, not source capability.
- Path A (overlay) > Path B (alternative library / paid).
- FBref `competition_name` strings must match exactly (em-dash gotcha).
- "Quick fix" budget: cap at cheapest attempt; skip workaround if not
  resolved; bank as known gap.

From S21:
- **Jan 2026 FBref/Opta termination** is a permanent industry fact.
  xG missing from FBref output is not a bug.
- **Free-only path accepted** for non-Understat / non-StatsBomb comps,
  no xG. Document, don't hide.
- **StatsBomb is a separate later track** for major intl tournaments
  (event-level data) — different schema, different loader.
- soccerdata's `read_team_match_stats` is all-comps contaminated;
  filter strategy lives in loader (URL substring + round enum cross-check).
- soccerdata's `_parse_table` doesn't filter columns — missing columns
  reflect what FBref serves, nothing more.
- Cross-source `player_id` strategy: defer entirely (option c).

From S22 (schema delta design):
- **Option C (source-separated FBref fact tables)** is the integration
  architecture — don't weld shape-only FBref rows into xG-dense
  Understat tables. Understat fact tables stay untouched.
- **Surrogate `game_id`, not VARCHAR** — never recreate FK-referenced
  fact tables when an additive surrogate path exists. The "no xG" gap
  is structural; let the schema show it (separate tables), don't hide
  it as NULLs.
- Migration is additive-only by construction → no DuckDB FK-block
  gotchas in play.
- Loader carries all parsing (surrogate id, schedule-membership filter,
  score parse, MultiIndex flatten + fail-loud map, source-aware
  position policy, age→DOB). `FBREF_COL_MAP` fail-loud is the
  FBref-drift early-warning.
- Name `stage` not `round` (DuckDB `ROUND()` clash).

## Commit message (for S21 close)

```
S21: FBref overlay for UCL committed; Path A probes done; xG gap acknowledged

Path A (FBref via soccerdata overlay) confirmed end-to-end for UCL via
empirical probes. In-repo overlay + setup script committed. xG turned
out to be unavailable via FBref industry-wide as of Jan 2026 — banked
as known constraint and accepted; free-only path adopted with documented
gaps for UCL/EL/Conference/qualifiers/friendlies. StatsBomb deferred as
separate S23+ track for major intl tournaments.

New files:
  data/config/league_dict.json
  src/tools/setup_soccerdata_overlay.py
  src/load/v2_ingest/_probe_UCL_team_player_shapes.py
  src/load/v2_ingest/_probe_UCL_team_player_extended.py
  docs/v104_ingest_competitions.md

Updated:
  Claude.md           (FBref/Opta termination, soccerdata gotchas,
                       in-repo overlay pattern, 70-min wall observation)
  docs/session_state.md  (S21 close)

Phase 2c probe findings:
  read_team_match_stats stat_type='schedule' for UCL → 1121 rows
    (all_comps URL contamination; EFL Cup etc mixed in; league=<NA>).
  read_team_match_stats stat_type='shooting' for UCL → 1121 rows,
    Standard subgroup only (no Expected/xG — Jan 2026 termination).
  read_player_match_stats stat_type='summary' for UCL → 5826 rows
    across 189 games / 878 players; Performance subgroup only;
    league correctly tagged 'UEFA-Champions League'.
  Wall time observed: ~70 min for one UCL season (vs 22-min estimate).

S22 picks up at schema delta design (step 3 of active task).

Refs: docs/v104_ingest_competitions.md, docs/session_state.md
```

## References

- soccerdata GitHub: https://github.com/probberechts/soccerdata
- soccerdata FBref module:
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/fbref.py`
  Key lines: 145–188 (`read_leagues`), 339–467 (`read_team_match_stats`),
  703–807 (`read_player_match_stats`), 1037–1064 (`_parse_table`).
- soccerdata custom overlay logic: `_config.py:184–193`.
- FBref/Opta termination (Jan 20, 2026):
  https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/
  https://ricardoheredia.substack.com/p/farewell-fbref-advanced-stats-when
- StatsBomb Open Data: https://github.com/statsbomb/open-data
  competitions.json verified S21.
- StatsBombPy: https://github.com/statsbomb/statsbombpy
- fotmob-api (likely broken): https://github.com/C-Roensholt/fotmob-api
- api-football pricing: https://www.api-football.com/pricing
- FBref competition catalog (cached): `~/soccerdata/data/FBref/leagues.html`
  158 competitions across 9 tables.
- Related Understat parser issue (still open, distinct from S21
  findings): https://github.com/probberechts/soccerdata/issues/904
