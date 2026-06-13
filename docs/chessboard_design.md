# Chessboard (stage 2) — tactical zone model design

**Status:** design, started S30 (2026-06-12). Brainstorm-driven, captures
decisions as they lock. Implements stage 2 of `analysis_pipeline_design.md`:
turn (formation + playstyle + 11 adjusted-attribute vectors) per team into a
team **xScoreline** via zone-by-zone battles, validated against StatsBomb spatial
truth. Consumes `player_adjusted_attributes_wide` (S29). Governing rule: a
**parameterised tactical prior, not a black box** — hand-built structure,
data-calibrated, explainable end to end.

Open knobs flagged **[OPEN]**; everything else agreed.

---

## Decision 1 — zone geometry (LOCKED S30)

**Board = 6 longitudinal bands × 5 lateral lanes = 30 zones.**

- **6 bands** (3 per half, mirrored around halfway). Resolution spent on the
  *length* axis on purpose: the xT gradient runs almost entirely lengthwise
  (danger rockets toward goal, barely changes across a band), so longitudinal
  bands capture the most value variance. Mirror symmetry makes the board
  **orientable** — build priors once for a team attacking "up"; the opponent uses
  the same board flipped. Top band = the danger zone (absorbs the "separate box?"
  question).
- **5 lanes** = 2 wings · 2 half-spaces · 1 central spine (canonical positional
  play). Chosen over 4 to (a) keep the striker-vs-CB central duel in its own lane,
  (b) distinguish **RW (wing lane) vs AMR/inside-forward (half-space lane)** — the
  same distinction our position-group work flagged finally does work here, and
  (c) make midfield battles richer (central + half-space × middle bands).
- **xT supplies value weight per zone**: collapse Karun Singh's fine 16×12 xT
  surface onto the 30 zones (sum/avg) → each zone carries a "how dangerous is
  possession here" multiplier. (https://karun.in/blog/expected-threat.html)
- **Two geometries retained:** **P1 = 6×5 = 30** (primary, canonical 5-lane).
  **P2 = 6×4 = 24** (fallback — inside-merged 4 lanes) kept for a complexity
  ablation / comparison. Build P1; keep P2 as a coarser variant to fall back to or
  benchmark against if 30 cells prove unwieldy in practice.

### Item 1 implementation — zone grid + xT value (LOCKED S32)

**Geometry as config** (`data/config/zone_grid.json`), on the StatsBomb 120×80
pitch, in attack-orientation (StatsBomb normalises the acting team to +x — no
half-time flip, confirmed S31; the opponent overlay reflects the board, D1's
orientability):
- **6 bands** = equal sixths of x: edges `[0,20,40,60,80,100,120]`, B1 own-defensive
  → B6 opp-box (B6 `x≥100` ≈ penalty area). *Banked tunable:* align bands to the
  18-yard line instead of equal sixths if validation wants it.
- **5 lanes** = y edges `[18,30,50,62]` → LW · LHS · C · RHS · RW. Wing bounds
  **reuse the S31 width-metric channels** (`y≤18 / y≥62`) for consistency.
- `zone_id = band*5 + lane`, 0–29.

**xT source = empirical, estimated natively at our 30 zones** from the StatsBomb
intl events (NOT collapsed from Karun's 16×12 — that's English club football, and
the transition structure of international tournament play is precisely the signal
we want). Markov xT: `xT(z) = s(z)·g(z) + m(z)·Σ T(z→z')·xT(z')`, solved by value
iteration. Estimated from 313,731 completed pass+carry moves (transition `T`) +
shots/goals per zone (`s`,`g`). **Karun's published surface = a shrinkage prior**
for sparse cells only (https://karun.in/blog/expected-threat.html).

*Viability verified S32 (`_probe`, read-only):* per-origin-zone outflow min 1,382
/ median 11,060 (every zone estimable); 900-cell matrix legitimately sparse
(719 nonzero — balls move locally, ~15 real dest-edges/zone), not a data gap;
shots/goals concentrate B5–B6 (1,453/3,379 shots, 2.5%→16% finishing) as xT needs.

**Zone-value contract (the item-8 interface that fixed this choice):** a zone's
value is in **goal-probability units**, so the battle layer can compute
`zone contribution ≈ control × xT(zone) × usage` and sum to team xG. Decomposed
empirical inputs, kept at their proper grain: *transition* → inside xT (team-
international events); *team zone-usage* → team layer (touch/pass density per
zone); *player chain* (xGChain/xGBuildup/xA, club per-player) → player-weighting
leg ONLY — never mixed into team flow (grain discipline, per D2).

### Finding for item 8 — transition/turnover value (S32, `_probe_goal_traceback.py`)

Tracing all open-play goals back through the StatsBomb event stream surfaced a
result that shapes the battle layer (NOT item 1): **225/404 = 56% of open-play
goals are sparked by a turnover** — the scoring team *won* the ball to start the
possession. The regain/spark zones are **anti-correlated with the clean-possession
xT surface** (Spearman ≈ −0.61): 62% of regains sit in wide + half-space lanes,
plus a deep-central cluster (win-it-deep-and-counter).

Implication: clean-possession Markov xT (item 1) **structurally cannot** value
transition danger — and it shouldn't try to. The static xT surface stays the
"value of a controlled ball at z" weight. **Transition/turnover value belongs in
the battle layer (item 8):** a contested ball or turnover in an advanced
wide/half-space zone carries danger for *both* teams, so zone resolution should
carry a recovery/transition term (recovery-credited, or a two-team value where the
ball can flip), not only sustained-possession control. This is why the wide/half-
space "chaos" zones matter even though their clean xT is low. **Bank for item-8
design.** (Probe caveat: its raw-stream grid still has a residual coordinate-frame
bug — the L/R flip must key on the acting `team`, not `possession_team`; the regain
grid + 56% headline are clean (scorer-frame), the raw last-5 grid is not. Probe is
deletable; the finding is banked here.)

### Finding for item 8 — offside is a relational gate, NOT an occupancy clip (S33)

Offside must be modelled, but it belongs in the **battle layer**, not the
occupancy assembly, because it is **relational**: a striker is offside only
relative to the *opponent's* last line, and a per-team kernel has no knowledge
of the other team's board. Two principles locked S33:

- **Enter offside ONCE, at the contest — do NOT clip attacking occupancy.**
  `occupancy_base` is empirical StatsBomb positions, so the *average* attacker is
  already onside-realistic (this is why ST is anchored at band 4.5, not 5). A
  second occupancy clip would **double-count** the discipline already in the data,
  and would be non-relational (a constant blind to the actual opponent line) and
  would wrongly forbid the legal, common case of a striker in B6 played onside.
  So item 8 leaves the assembled boards untouched and gates **threat**, not
  presence: an attacker's open-play threat in bands ahead of the offside line is
  suppressed/discounted.

- **The offside line = the REARMOST outfield defender, not the team mean/median
  (`line_height`).** The `line_height` axis is the *average* defensive engagement
  height, dragged forward by pressing mids/forwards; using it as the offside line
  would set the line far too high and flag onside attackers. The law's line is the
  **second-last opponent** (GK is last) — i.e. the deepest outfield defender (the
  CBs). Build it carefully:
  1. **Derive the line from the rearmost defender's OCCUPANCY** (the deepest CB's
     kernel), read off the defending team's *assembled* board — never from the
     `line_height` axis directly.
  2. **It's a distribution, not a point** — the deepest CB holds a band *with
     spread*, and the line moves play-to-play → offside gating should be
     **probabilistic**: attacker mass at band `b` is onside with a probability set
     by the rearmost-defender band distribution, not a hard cutoff.
  3. **`line_height` enters only indirectly** — a high line shifts the CB kernel up
     (item 4), so the line read off that shifted kernel is higher. The axis matters
     through *where it puts the back line*, never as the line itself.

- **Pace modulates the gate** (ties to the banked item-5 "danger-zone nudge"):
  Rapid/Quick Step = better at timing runs to stay onside while threatening the
  highest band → fast attackers beat the trap more often. So the pace nudge is a
  modulation of the offside gate, not a free pass. Banked for item-8 design.

### Item 2 implementation — position → home anchor (LOCKED S32)

Canonical vocab = the **`positions` table** (23 `position_code`s + `position_class`
+ `flank`), which `formation_slots` deploys; StatsBomb's 23 positions map ~1:1
for validation. Config: `data/config/position_home_cells.json`.

**Home is a CONTINUOUS anchor `(band_pos, lane_pos)`, not a discrete cell.**
Integers = cell centres; **half-values = the edge between two cells**. This
unifies point / edge / vertex homes into one primitive and is the centre the
item-3 kernel spreads from. `band_pos∈[0,5]` (B1→B6), `lane_pos∈[0,4]`
(LW·LHS·C·RHS·RW). Lane side from `flank`, with the key nuance: **central
defenders/mids carrying an L/R flank (LCB/RCB, LCM/RCM, LAM/RAM) sit in the
HALF-SPACES**; wide defenders/wingers/wide-mids (LB/RB, LWB/RWB, LW/RW, LM/RM)
in the WING lanes. Clean central spine GK(0)→CB(1)→DM(2)→CM(3)→CAM(3.5)→ST(4.5).
Edge anchors (S32 design w/ maintainer): **ST/FW = B5/B6 edge** (band 4.5 —
offside-realistic, not camped in the box), **CAM = B4/B5 edge** (3.5, drops
between lines), **LWB/RWB = B3/B4 edge** (2.5). LM/RM flagged playstyle-sensitive
(wing vs advanced vs half-space) — resolved by SHIFT in item 4.

### Item 3 rule banked — multiplicity lateral fan

A code's anchor is identical regardless of how many are fielded. When a formation
deploys **N>1 slots of the same central code** (e.g. 4-2-3-1 has two `DM`; a
two-`ST` or two-`CM` system), item 3 **fans them laterally** around the anchor's
`lane_pos` at assembly time (two `ST` → `(4.5, 1.5)` & `(4.5, 2.5)`, i.e. the
B5/B6 × C/half-space corners; two `DM`/`CM` → the C/LHS & C/RHS edges). This is a
formation-assembly property, kept OUT of the static item-2 map.

## Complexity-management principle (LOCKED S30) — the answer to "30 cells is a lot"

The maintainer's real concern: hand-built tactical models die of complexity. Three
rules keep 30 cells tractable:

1. **Parameterise, don't enumerate.** We do NOT author 30 bespoke cells. Priors are
   *functions* of `(lane-type, band, phase)` from a small set of archetypes
   (wide-attack, half-space-attack, central-final, central-build, deep-defensive,
   …). Left/right symmetry collapses 5 lanes → 3 lane-types (wing, half-space,
   central); orientation reuse collapses both teams → one attacking direction. Net
   distinct design surface ≈ **3 lane-types × 6 bands**, not 30 × 2 teams.
2. **Occupancy is derived, not hand-set per cell.** Reuse existing `formations` +
   `formation_slots` (formation→slot→`position_code`); add a **position→(lane,band)**
   occupancy map per phase. Hand-built part is keyed by **~15 position codes**, not
   30 cells.
3. **Stage the build.** Base board + occupancy + attribute battles FIRST
   (formation vs formation, neutral playstyle) → validate vs StatsBomb → THEN add
   playstyle modifiers. Don't build all six agenda items at once.

## The spine — per-player graded zone occupancy (S30 framing)

The core object of the model: each player has **primary / secondary / tertiary
zones** (a graded, weighted occupancy across the 30 cells, per phase), NOT a binary
"in/out." A player's attributes enter each zone's battle **weighted by their tier**
there. The tiered occupancy is built as a chain:

```
final per-player tiered zones  =  BASE(formation)  ⊕  SHIFT(team playstyle)  ⊕  TWEAK(player EA playstyle)
```

Validated/calibrated against **StatsBomb touch maps** (the "empirical-evidence
based" leg the maintainer asked for, vs the "theoretical EA/formation" leg).
Everything below feeds this spine.

## Design agenda (dependency order; maps the maintainer's S30 items)
1. Zone geometry — **LOCKED** (above). [P1 6×5 / P2 6×4]
2. **Team playstyle taxonomy** [maintainer #1] — define styles as a small vector of
   continuous tactical **axes** + named archetype presets (parameterise, don't
   enumerate). ← proposed next.
3. **Base occupancy** — formation → per-player BASE tiered zones, neutral style.
   Reuse `formations`/`formation_slots`; needs a quick observation of what those
   tables hold (coords vs position codes).
4. **Playstyle → occupancy/zones** [maintainer #2] — how the team-style axes SHIFT
   base occupancy + reweight zone values.
5. **Player EA playstyles** [maintainer #3] — map EA PlayStyle tags → per-position
   personal TWEAKs to occupancy + attribute emphasis.
6. **Synthesis** [maintainer #5] — combine 3⊕4⊕5 → final per-player primary/
   secondary/tertiary zones; define what each tier *means* numerically (occupancy
   weight + attribute weight), theoretical (EA) vs empirical (StatsBomb) legs.
7. **Attribute→zone relevance** [maintainer #4] — which FIFA attributes matter per
   `(lane-type, band, phase)`, modulated by tier + playstyles → the zonal-battle
   inputs.
8. **Battle resolution + aggregation → xScoreline** — 1v1 vs aggregate contest;
   per-zone xThreat → team xG → scoreline distribution (bivariate-Poisson
   precedent, md38 work) → sim. StatsBomb spatial validation loop throughout.

## Decision 2 — team playstyle: axes + hybrid sourcing (LOCKED S30)

Playstyle = a vector on **5 continuous tactical axes** (0–1 dials); archetypes are
presets, not hardcoded styles (parameterise, don't enumerate):
1. **Directness/tempo** — patient short ↔ vertical/long & fast.
2. **Width** — central/half-space ↔ wing & wide.
3. **Line height** — deep block ↔ high line.
4. **Press intensity** — passive contain ↔ gegenpress.
5. **Possession share** — reactive/counter ↔ possession-dominant.

Presets e.g. tiki-taka (lo-dir, central, hi-line, hi-press, hi-poss); low-block
counter (hi-dir, neutral, deep, lo-press, lo-poss); gegenpress (mid-dir, wide-ish,
hi-line, max-press, hi-ish-poss). Each axis later drives occupancy/zone modifiers
(width→wing vs half-space; line→band shift; press→recovery band; etc.).

**Sourcing = hybrid (prior + empirical, coverage-weighted — same shape as the
EA↔empirical blend):**
- **Empirical leg** — from StatsBomb intl events (WC22/Euro24/Copa24/AFCON23 = real
  national-team matches, unlike our club data). Per-axis derivable metric:
  (1) directness → median pass length + %forward + possession-to-shot speed;
  (2) width → lateral touch/pass share; (3) line height → mean vertical location of
  defensive actions (360 frames for WC22/Euro24); (4) press → **PPDA**;
  (5) possession → possession %. Normalise each 0–1 across teams-with-data.
- **Prior leg** — hand-assigned current-2026 identity on the 5 axes. Burden is
  bounded: high-data teams lean empirical, so hand-tuning concentrates on the
  no-StatsBomb dark set (~AFC/Gulf), ~a dozen sides.
- **Blend** — `axis = (1−λ_team)·prior + λ_team·empirical`; `λ_team` = intl-match
  coverage, recency-weighted (2024 tournaments ≻ WC22); no data → pure prior.
- **Caveat (banked):** national-team style is coach-dependent and flips between
  cycles. Prior carries the current identity; empirical recency-weighted to the
  latest tournament; lean prior where the coach changed since the last StatsBomb
  tournament (add a per-team "coach unchanged since?" flag later).

## Decision 3 — base occupancy, attack-phase PRIMARY (partial-LOCKED S30)

Neutral-style, single-striker default. Bands (team attacking "up"): B1 own box ·
B2 own build-up · B3 own mid-third · B4 opp mid-third · B5 final approach · B6 opp
box. Lanes: LW · LH · C · RH · RW. Mapped on the real 23-code vocabulary.

| code | lane,band | code | lane,band |
|---|---|---|---|
| GK | C,B1 | DM | C,B3 |
| CB/DF | C,B2 | CM/MF | C,B4 |
| LCB | LH,B2 | LCM | LH,B4 |
| RCB | RH,B2 | RCM | RH,B4 |
| LB | LW,B3 | LAM | LH,B5 |
| RB | RW,B3 | RAM | RH,B5 |
| LWB | LW,B4 | CAM | C,B5 |
| RWB | RW,B4 | LW | LW,B5 |
| LM | LW,B4 * | RW | RW,B5 |
| RM | RW,B4 * | FW/ST | C,B6 ** |

Locked calls (S30): LCB/RCB **home = half-space** (spine handled by secondary/
tertiary tiers, not the base lane); CAM **central**; FB→B3 / WB→B4 / winger→B5
heights agreed.

**Context-dependent (NOT fixed in base — resolved by later operators):**
- `*` **LM/RM lane** depends on formation + width axis. Base = **wing (neutral)**;
  the team-playstyle WIDTH **SHIFT** (item 4) inverts them toward the half-space.
  Exact shift magnitude deliberated at item 4.
- `**` **ST/FW** base varies by **count + player role**. Default = C,B6 (lone 9).
  Two context rules: (a) **front-two split** when a formation has 2 ST (e.g. 4-4-2,
  3-5-2, 5-3-2, 4-4-2) — the pair doesn't stack; one stays focal (C,B6), one
  drops/links (C,B5) or splits to a half-space; (b) **false-9** = player-playstyle
  TWEAK (item 5) dropping the striker to ~C,B5/B4 and vacating B6. → motivates the
  tier + context-rule mechanism (next).

**Still open:** secondary/tertiary tiers (where the spine, strike-pairs, false-9,
and inversions actually live), the **defence-phase** map (≈ shift down ~2 bands,
wide players narrow inward), and tier *semantics* (what primary/secondary/tertiary
mean numerically — occupancy weight + attribute weight).

## Decision 4 — occupancy as role kernels + tier semantics (LOCKED S30)

**Presence budget = 1.0 per player**, distributed across a *territory* of cells
(not 3 pins). Each cell's weight does **double duty**: (a) occupancy share — who
contests the zone — and (b) the scalar on that player's attributes in that zone's
battle. Zone team-strength for an attribute = `Σ_players (attribute × weight_in_zone)`.

**Occupancy = a role spread kernel** (parameterise, don't hand-list per code):
- Anchored at the home cell (Decision 3 base map).
- Presence spreads to neighbours, weight decaying by tactical distance, shaped by
  **4 role dials: forward reach · backward reach · lateral reach · spread
  (tight↔roamy)**. Normalised to sum 1.
- **Tiers (home / primary / secondary / tertiary) = weight bands of the kernel** —
  a readable slicing, not a separate structure. ~5–10 cells/player; roamers
  (box-to-box) get wide kernels, CBs tight ones.
- **~6 role templates** cover all 23 codes: CB (tight, back+lateral, minimal fwd) ·
  DM (central, moderate) · CM/box-to-box (wide, big fwd+back, into half-spaces +
  wings) · FB/WB (vertical up own wing) · W/AM (wing + cut-inside, fwd-skewed) ·
  ST (lateral across front + drop to link).

Worked example — box-to-box LCM (home LH-B4): home LH-B4 .24 | primary C-B4 .14,
LH-B3 .14 | secondary C-B3/LH-B5/LW-B4 ~.08 | tertiary C-B5/LH-B2/LW-B5/C-B2
~.04–.05. ≈10 cells, Σ=1. CB ≈6 cells, none in the opponent half.

**Scope: OPEN PLAY only.** Defender forward reach = a band or two ahead of base,
NOT the attacking third. **Set-pieces = separate phase overlay, deferred** (CBs in
the opp box for corners would distort open-play battles if baked in).

**Reshaping (items 4–5, next):** team-playstyle SHIFT + player-playstyle TWEAK
operate by *reshaping the kernel* — width stretches it laterally, line height shifts
it up/down, false-9 pulls the striker's kernel back — never by editing cell lists.

## Decision 5 — team playstyle → kernel transforms (LOCKED S30)

Each role has **two kernels**: an **attack-phase** and a **defence-phase** shape
(defence = deeper, narrower, more compact). The 5 axes act as geometric transforms
— they warp the cloud, never edit cell lists:

- **Possession share `p`** → the **phase blend**: time-averaged occupancy =
  `p·attack_kernel + (1−p)·defence_kernel`. Possession side lives in its attack
  shape; a counter side in its defence shape.
- **Line height** → **vertical translation** (±1–2 bands) of both kernels (the block
  slides up/down the pitch).
- **Width** → **lateral reach + wide-player lane bias** (high → FB/W to wing lanes;
  low → tuck into half-spaces). Resolves LM/RM: weight moves wing↔half-space.
- **Press intensity** → forward shift / compression of the **defence kernel only**
  (recovery band climbs into the opp half for a gegenpress; deep block when low).
- **Directness** → thins mid-third dwell + increases vertical separation between
  lines; its *main* effect is **battle tempo** (item 8, downstream), light on
  occupancy.

Subtlety banked: **line height = where the block sits; press = how far it jumps
forward out of possession** (they correlate but are distinct dials).

## Decision 6 — player EA PlayStyles → families (LOCKED S30, data-validated)

36 distinct EA PlayStyles bucketed into **5 outfield families** (+ 2 carve-outs).
Modal analysis (prevalence by `position_class`) **validates** the family→role
attachment: DEF clusters defending, FWD clusters finishing/movement/dribbling, MID
mixes passing/dribbling/movement (Relentless = the box-to-box roamer), GK separate.

| family | effect | tags |
|---|---|---|
| **Movement** | kernel tweak (fwd reach / spread / press-shift) | Rapid, Quick Step, Relentless, Press Proven |
| **Finishing** | attr emphasis: finishing/shot_power/att-heading, box | Finesse Shot, Power Shot, Low Driven Shot, Chip Shot, Acrobatic, Precision Header |
| **Passing/creation** | attr emphasis: passing/vision/crossing; build-up/half-space/wide | Long Ball Pass, Pinged Pass, Incisive Pass, Inventive, Tiki Taka, First Touch, Whipped Pass |
| **Dribbling** | attr emphasis: dribbling/ball_control, att lanes (+carry tweak) | Technical, Trickster, Gamechanger |
| **Defending** | attr emphasis: tackle/intercept/def-heading (+press tweak) | Intercept, Anticipate, Slide Tackle, Block, Jockey, Bruiser, Enforcer, Aerial Fortress |
| *GK (parked, GK track)* | with the GK model | Footwork, Cross Claimer, Far Throw, Deflector, Rush Out, Far Reach |
| *Set-piece (deferred overlay)* | corners/FKs/throws | Dead Ball, Long Throw |

Nuance forced by data: **Aerial Fortress** (defensive aerial; DEF/MID) vs
**Precision Header** (attacking aerial; FWD) — same body part, opposite families.
`tier` (base/plus) sets effect magnitude; effects kept **modest** (qualitative/
positional layer only — never re-inflate the already-adjusted attribute values).
Player emphasis **compounds** with the team-generic zone-attribute relevance (item 7).

## Decision 7 — attribute→zone relevance (LOCKED S30)

Team-generic matrix: per zone archetype `(lane-type × band-role)` (~6, not 30
cells), which of the 29 attributes the **attacking** team threatens with and the
**defending** team stops with. Player-playstyle emphasis (D6) compounds per player.

| zone archetype | attacking attrs | defending attrs |
|---|---|---|
| Deep build (central/HS, B1–B2) | short_pass, long_pass, composure, vision, ball_control | stamina, aggression, acceleration, positioning (press) |
| Central midfield (C, B3–B4) | short_pass, vision, composure, ball_control | interceptions, standing_tackle, aggression, positioning |
| Wide progression (wing, B3–B4) | sprint_speed, acceleration, dribbling, stamina | sprint_speed, standing_tackle, positioning, stamina |
| Half-space creation (HS, B4–B5) | vision, short_pass, ball_control, dribbling, long_shots | interceptions, def_awareness, positioning, standing_tackle |
| Wide final/byline (wing, B5–B6) | dribbling, agility, crossing, acceleration | sliding_tackle, standing_tackle, sprint_speed, positioning |
| Box/central final (C+HS, B6) | finishing, composure, reactions, heading, shot_power, off-ball positioning | def_awareness, heading, standing_tackle, interceptions, strength (+GK) |

- **Numeric weights within each cell deferred to tuning-on-data** (same posture as
  the EA bucket weights): agree the attribute SET now, fit weights later.
- **GK interface:** the box archetype has a keeper behind it → wires to the GK
  track when that's built.

## References
- xT (value surface): https://karun.in/blog/expected-threat.html
- Positional play / 5-lane grid + half-spaces:
  https://learning.coachesvoice.com/cv/positional-play-football-tactics-explained-guardiola-cruyff-manchester-city/
  https://breakingthelines.com/tactical-analysis/what-is-juego-de-posicion/
- StatsBomb Open (spatial validation set): https://github.com/statsbomb/open-data
- `analysis_pipeline_design.md` (stage 2 vision), `player_adjusted_attributes_wide` (S29 input).
