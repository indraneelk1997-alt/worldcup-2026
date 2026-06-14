# Chessboard Item 8 — Zone Aggregation → xScoreline

> Designed S36 with the maintainer. The layer that turns the item-7 **1v1**
> zone battle into a per-zone **team** contest, then assembles 30 zones into two
> team expected-goal numbers and a scoreline. Consumes item-6 `team_boards()`,
> item-7 `zone_battle.resolve_context`, `zone_xt` (item 1), and
> `team_playstyle_blended` (D2). Build incrementally; **design first, code after.**

## Pipeline shape (end to end)

```
item-6 team_boards  ─┐
                     ├─► (A) occupancy-weighted aggregation  → per-zone team contest (1 per direction)
item-7 zone battle  ─┘
                              │  P(win)_z  ∈ [0,1]   (chance CREATION)
                              ▼
        (B) conversion layer:  × conv_rel(finisher) vs GK shot-stopping   (chance CONVERSION)
                              ▼
        (C) value-weight:      × zone_xt_z   and   × entry_share_z
                              ▼
        (D) VOLUME calibration: × sequences-per-match (measured anchor, poss/tempo-modulated)
                              ▼
                     team_xG  (one number per team)
                              ▼
        (E) bivariate Poisson (md38 precedent) → scoreline distribution → sim
```

Each stage is a separate, individually-validatable piece. Build A first (it has
the cleanest validation: a real team's board vs another's, eyeballed), then B–E.

---

## (A) Occupancy-weighted aggregation — **LOCKED**

The item-7 resolver is strictly 1v1 (`resolve_context(att, dfn, …)`). Lift it to a
team contest by replacing the single-player `_side_score` with an
**occupancy-weighted combine over every player present in the zone**.

### Inputs already exist
`team_boards(slots)` → `{'attack': board, 'defence': board}`; each board maps
`zone_id (0–29) → [{slot_no, position_code, ea_id, weight}, …]` sorted desc. The
**`weight` field IS `occ(p, zone, phase)`** — already computed by items 4–6. No new
occupancy work; aggregation just consumes the player list per zone.

### Combine rule — β-parametrized sum
For one side, one duel:

```
side = (Σ_p occ_p) ^ β  ·  [ Σ_p occ_p · q_p  /  Σ_p occ_p ]
            └ numbers ┘        └──── occ-weighted mean quality ────┘
q_p = per-player weighted-mean attr score (the current item-7 _side_score), incl. family_mult
```

- **β = 1** (default) ≡ the item-7 doc's literal `Σ_p occ_p · q_p` sum. Numerical
  overloads count linearly: a packed box out-defends a lone striker, which is what
  BT should reward.
- **β = 0** = pure occ-weighted mean → discards numbers entirely (a lone elite
  striker would beat five average defenders). Rejected as a default; kept only as
  the β=0 end of the dial.
- **0 < β < 1** = overloads with diminishing returns. β is a **tunable** in
  `zone_battle.json`, calibrated vs StatsBomb later. Default β = 1.

**Why this resolves the maintainer's busy/neglected-zone caveat:** the directional
pairing (below) runs *attack board vs opponent's defence board* in each zone, so a
team that stacks an under-occupied opponent zone gets a numbers edge there for free.
"Exploit the thin zone" is emergent, not hand-coded.

### 30 → 9 fold (mechanical)
Board zones are 0–29 (`band*5+lane`, 6×5). Item-7 authors 9 zones
(3 lane-types × 3 levels). Map each board zone → one authored config by mirror-fold
(`B1↔B6, B2↔B5, B3↔B4`; lane `LW≡RW, LHS≡RHS, C`) **plus** the context:
attacking half → `attack_vs_defense`, own half → `buildup_vs_pressure`. Pure lookup.
(Middle-third pairing still TBD per item-7 — resolve when we wire those bands.)

### Directional pairing (mechanical)
A zone contest = Team A's **attack** board (zone Z) vs Team B's **defence** board
(mirror of Z). Run both directions → two per-zone contests. Item 8 blends them via
possession (deferred from item-6 decision B).

### Refactor seam
New `_team_side_score(players_with_occ, attr_w, boost, fmult, beta)` replaces the
single-player `_side_score` inside `resolve_stage`. BT / stage weighting / threat
math downstream unchanged. The 1v1 `--probe` stays working (a 1-player board is the
degenerate case).

---

## (B) Conversion layer — creation × conversion — **DECISION + one OPEN fork**

**Problem (maintainer, S36):** item-7 `threat` is a **probability** of prevailing.
It does not carry the **value of winning**. Two strikers with equal win-prob in the
same zone are currently equally dangerous — so in-form Haaland (wins 0.3) and cold
Havertz (wins 0.4) come out wrong. The fix is to separate the two football events:

- **Creation** = the item-7 zone battle → `P(team generates a quality chance here)`.
- **Conversion** = the quality of that chance given it's created → an `xG-per-chance`
  multiplier driven by the finisher's output attrs, contested by the **GK**.

### Conversion is a RELATIVE multiplier — **LOCKED**
`zone_xt` (item 1, Markov surface) is already denominated in **expected goals at
league-average conversion**. So conversion must NOT stack a second absolute xG; it
**re-scales** the baked-in average:

```
conv_rel ≈ 1.0  for an average finisher,  > 1 Haaland,  < 1 cold Havertz
```

This is also where the empirical form data does its *second, more powerful* job:
form nudges the duel probability (already) **and** scales chance value here. Centred
at 1.0 so it re-weights rather than double-discounts the magnitude.

### GK enters here — **DECISION**
The conversion multiplier is a duel: finisher output attrs vs GK shot-stopping
(reflexes / diving / positioning / handling). This gives the GK its first real role
without the full GK track (build-up distribution, claiming crosses stay deferred).
`conv_rel = f(finisher) / g(GK)` shape, BT-style, centred so an average finisher vs
an average GK ≈ 1.0.

### RESOLVED (S37) — partition the attrs + scope conversion to the shot component
**Fork resolved: PARTITION** (maintainer, S37). `finishing` leaves the box duels and
moves to conversion; each attribute keeps exactly one job.

- **Box main duel** becomes "get the shot away vs the block" → `composure` /
  `ball_control` vs `standing_tackle` / `def_awareness` (finishing removed; the
  Finishing-family `att_boost` moves to conversion). Re-author the ~4 shooting zones
  that currently put `finishing` in the att duel: central_L1, the edge-of-box
  long-shot zone, the half-space finesse zone, and the dribble-finish zone.
- **Conversion** = "beat the keeper" → finisher `finishing` + `shot_power`
  (occ-weighted over attackers present, + Finishing-family boost) vs GK
  `reflexes / diving / positioning / handling`. GKs have **no adjusted attrs**
  (separate track) → pull raw EA from `ea_fc26_player`.

**Form:** `conv_rel = 2 · BT(finish_score, gk_score)` → centred **1.0** (avg-vs-avg
BT = 0.5), range (0, 2), gain tunable. It re-scales `zone_xt`'s baked-in *average*
conversion `g(z)`, so an average finisher leaves value untouched.

**Scope — only the shot component (grounded in `derive_zone_xt`):**
`xt(z) = s(z)·g(z) + m(z)·Σ T·xt`. The immediate shot value is `s·g`; the rest is
progression. So conversion weights by **`shot_share_z = s(z)·g(z) / xt(z)`** (both are
`zone_xt` columns): box ≈ 0.75 → conversion bites; deep zones ≈ 0 → pure progression,
untouched. Applied per zone:

```
value_z *= (1 − shot_share_z) + shot_share_z · conv_rel
```

v1 uses one `conv_rel` (finishing+shot_power) across shooting zones; zone-specific
conversion attrs (box→finishing, edge→long_shots) banked as a refinement.

---

## (C) Value-weight by zone_xt — **LOCKED (mechanics), weights to calibrate**

Each per-zone creation×conversion is weighted by `zone_xt_z` (positional value) and
by `entry_share_z` (how often the team's attacks reach that zone — proxied by the
team's own attacking occupancy mass distribution, normalised over zones). Summing the
30 weighted per-zone values gives a per-match **attacking-output index** (a small
decimal — correctly, this is per attacking *sequence*, not per match).

---

## (D) VOLUME calibration — lift the index to a scoreline — **DECISION**

The Σ-over-zones index is xG **per attacking sequence**. To reach a scoreline we
multiply by **sequences per match**:

```
team_xG (match) = VOLUME × Σ_zones [ entry_share_z · zone_xt_z · P(win)_z · conv_rel_z ]
```

### Route chosen: empirical anchor + one calibration constant (v1)
- **Measure, don't assert (rule 3):** compute real **goals/team/match** and
  **shots/team/match** from the four loaded StatsBomb tournaments
  (WC22 / Euro24 / Copa24 / AFCON23) — the anchor comes from our own data, not memory.
- Pick `VOLUME` so an **average matchup** reproduces that measured average.
- **Per-team modulation:** `possession` share and `directness` (already in
  `team_playstyle_blended`) scale `VOLUME` around the anchor — more possession /
  higher tempo → more sequences.

### Measured anchor (S36, from `statsbomb_event`, period<5, 398 team-matches)

| tournament | xG/tm | goals/tm | shots/tm | seqs/tm |
|---|---|---|---|---|
| WC22 | 1.218 | 1.320 | 11.35 | 86.6 |
| Euro24 | 1.184 | 1.049 | 12.90 | 78.8 |
| Copa24 | 1.153 | 1.078 | 11.73 | 84.3 |
| AFCON23 | 1.139 | 1.106 | 11.38 | 86.1 |
| **overall** | **1.178** | **1.156** | **11.82** | **84.1** |

- **Primary VOLUME target = ~1.18 xG per team-match.** `xg_pm` is tight across all
  four tournaments (1.14–1.22) → a *single global* VOLUME constant is justified;
  no per-tournament fudge needed. goals/shots are cross-checks.
- `goals_pm` validated the encoding (1.156/tm → ~2.31 goals/match; WC22 2.64,
  Euro24 2.10 — correctly the low-scoring outlier).
- **VOLUME is a fitted constant, not `seqs_pm`.** Fit it so an *average*-team
  attacking-value index reproduces ~1.18. Since `conv_rel` is centred at 1.0, the
  average-team index is ~invariant to conversion → VOLUME can be fit cleanly.
- **`seqs_pm = 84` is raw possessions** (incl. trivial clearances/single-touches).
  A "meaningful attacking sequence" filter (reaches final third / has progression)
  would sharpen the true volume count. **Banked refinement.**
- Reference index point: the S36 ENG-vs-NED sweep gave an attacking-value index of
  **0.00853** (ENG, above-average attack, pre-conversion). Calibrate against the
  *average* team, not this one.

### VOLUME fit — round-robin (S37)

- 47/48 nations assembled (1 dark squad skipped), **2,162 matchups**, greedy
  **quality×caps** XIs (selection score = 0.6·adjusted-role-rating-pct + 0.4·caps-pct;
  `selection_scores()` off `_probe_adjusted_ratings.build()`).
- index mean 0.00591 → **VOLUME = 1.178 / 0.00591 = 199.4**.
- **team_xG: mean 1.178 (by construction), std 0.588** | min 0.07, p10 0.53, p50 1.09,
  p90 1.95, **max 4.19**.
- **Read:** median matches empirical (1.09 vs 1.07), demolitions reach 4+ (max 4.19 vs
  4.32), **no 1-1 trap** (std 0.588 ≫ 0.3). Tails slightly compressed vs raw xG
  (p10 0.53 vs 0.32, p90 1.95 vs 2.29).
- vs effective-rate target 0.45: model slightly **wide** → Poisson would give
  var/mean ≈ 1 + 0.588²/1.178 ≈ **1.29** vs empirical 1.18 → ample spread (opposite of
  the 1-1 fear). In E: accept or apply mild shrinkage; definitive test = simulated goals
  dist vs empirical.
- VOLUME 199.4 is a fitted constant (round-robin all-48; refine matchup weighting +
  formation-per-team later). Promote to config when E lands.
- **Banked curiosity:** Vinícius Jr drops out of BRA's XI — likely a cross-source
  linkage / Understat-coverage gap (S27) excluding him from the adjusted-attrs pool,
  not a ranking issue. One-line check owed.

### Variance / spread — the SECOND calibration target (S37, 398 team-matches)

- **xG/tm distribution:** mean 1.178, **std 0.732** (std/mean 0.62), right-skewed —
  min 0.00, p10 0.32, p25 0.65, p50 1.07, p75 1.57, p90 2.29, **max 4.32**. Real
  demolitions (Germany 4.32) and no-shows (≤0.1) both exist → blowout potential is
  real; a too-narrow *model* xG spread is what would force everything to 1-1.
- **Goals only MILDLY overdispersed:** var/mean = **1.178** (Poisson = 1.0). Goals dist
  per tm: `0:134  1:138  2:81  3:30  4:9  5+:6`.
- **KEY inversion:** the xG-metric cross-match variance (0.536) *overstates* the scoring-
  RATE variance needed to reproduce goal variance. From var/mean: effective
  `Var(λ) = (1.178−1)·1.156 ≈ 0.21 → std(λ) ≈ 0.45`, vs raw xG std 0.73. **~2/3 of xG's
  spread doesn't reach the scoreline** (xg-sum inflates via shot volume/independence —
  e.g. Germany 4.32 on 31 shots). So **target the goals distribution, NOT the raw xG std.**
- **Finishing noise** (`goals−xG`): mean −0.02 (xg unbiased), **std 0.994** ≈ Poisson-
  consistent (Poisson would give ~1.09). → **plain bivariate Poisson is structurally
  adequate; NO negative-binomial / overdispersion term needed.** Variety comes from the
  team-xG spread, not from fattening Poisson.
- **Acceptance test for the sim (E):** reproduce the goals distribution above +
  var/mean ≈ 1.18 + the draw rate — NOT the raw xG std. Guards against BOTH the 1-1
  trap and over-blowout.
- **Outliers = volume and/or quality + heavy finishing noise:** Germany 4.32/31 shots
  (volume), Brazil 3.75/17 @ 0.22 xg/shot (quality); dominant teams routinely waste it
  (Argentina 3.54→2, 2.78→1; Czechia 2.87→1). Our model gets volume+quality from
  occupancy dominance in dangerous zones; Poisson supplies the wastefulness.

### Rejected for v1: full Markov possession-flow (→ v2)
Treating the zone win-probs as progression transitions so volume *emerges* is more
elegant and is the natural home for the **midfield-supply chain** (Vitinha/Bruno →
Leão). But it is exactly the sequential-flow model banked as v2. `zone_xt` already
prices *reaching* an advanced zone as valuable, so supply is implicitly rewarded in
v1; explicit chaining waits.

---

## (E) Scoreline — **bivariate Poisson (md38 precedent)**

Two `team_xG` numbers → bivariate Poisson → full scoreline distribution
(P(2–1), P(0–0), …) → match sim. Reuse the md38 bivariate-Poisson approach already
in the repo. Correlation term handles game-state coupling.

---

## Deferred / v2

- **Sequential possession-flow / supply chain** (midfield unlocks winger) — Markov
  flow over zones; replaces the VOLUME constant with emergent volume. (D-route B.)
- **Full GK track** — build-up distribution from the back, claiming crosses,
  sweeper-keeper line height. Only shot-stopping lands in v1 (layer B).
- **Set-piece overlay** — penalties / free_kick_accuracy / corner threat; parked.
- **Middle-third (L3) contest pairing** — buildup-vs-attack ambiguity at halfway
  (shared with item 7).
- **Game-state weighting** — line-height / volume shift when protecting a lead
  (banked S31).

## Parameters to calibrate vs StatsBomb (priors, not asserted truth)

`β` (overload exponent, default 1) · `conv_rel` scale + finisher/GK attr weights ·
`entry_share` definition (occupancy proxy vs measured entries) · `VOLUME` anchor +
possession/directness modulation slopes · bivariate-Poisson correlation. All start as
priors; tune against the loaded tournament data.

## Build order (each its own session-step, validated before the next)

1. **(A)** occupancy-weighted aggregation — refactor `_team_side_score`, 30→9 fold,
   directional pairing. Validate on a real board (e.g. ESP attack vs a back line).
2. **(D-anchor)** measure goals/shots per team-match from the 4 SB tournaments.
3. **(B)** conversion layer + GK shot-stopping; resolve the finishing double-count fork.
4. **(C)+(D)** value-weight + VOLUME → team_xG.
5. **(E)** bivariate Poisson → scoreline; calibrate against the measured anchor.
