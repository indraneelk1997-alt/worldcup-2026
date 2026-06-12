# Coverage, EA calibration & prior/shrinkage — design

**Status:** design, started S27 (2026-06-12). Design-first, captures the
S27 data-reconciliation + the agreed modelling spine: how we measure per-player
data coverage, de-bias the EA prior against empirical evidence, and blend
prior + empirical into the attribute estimates the chessboard/sim consume.
Companion to `analysis_pipeline_design.md` (the why) and `resolver_design.md`
(the links this builds on). No code beyond the read-only audit probe yet.

Open knobs are flagged **[OPEN]**; everything else is agreed S27.

---

## 1. The four data sources (what each actually carries)

Observed S27 from the live columns + StatsBomb event types. The model can draw
on four sources, in the **value order the maintainer set**: top-5 xG (1st) >
intl event-level (2nd) > EA prior (3rd) > European cups (4th, shape-only since
the Jan-2026 Opta termination killed FBref xG).

| Metric family | Understat top-5 | FBref cups | StatsBomb intl | EA prior |
|---|---|---|---|---|
| Goals / shots volume | ✅ | ✅ (+SoT) | ✅ events | ✅ |
| **Shot quality / xG** | ✅ `xg` | ❌ (Opta) | ✅ `shot_xg` | ~ finishing |
| Creation / xA / build-up | ✅ `xa`,`key_passes`,`xg_chain`,`xg_buildup` | ⚠️ assists only | ✅ derivable | ✅ passing/vision |
| **Tackles / interceptions** | ❌ | ✅ `tackles_won`,`interceptions` | ✅ events | ✅ defending |
| **Aerial duels** | ❌ | ❌ (Opta) | ✅ duel events | ✅ heading/strength |
| **Dribbles / carries** | ❌ | ❌ | ✅ carry/dribble events | ✅ dribbling/agility |
| **Pressing** | ❌ | ❌ | ✅ pressure events | ~ (no workrate col) |
| Discipline (fouls/cards) | ⚠️ cards only | ✅ fouls/cards/fouled | ✅ events | ~ aggression |
| GK | ❌ | (keepers stat_type not loaded) | ✅ GK events | ✅ 5 GK attrs |

**Structural shape of the data (the key lesson):**
- **Attacking is well-served** for club football (Understat xG, 504 players).
- **Defensive / duel / dribble / press is a club-football hole** — Understat
  has none; FBref cups patch only `tackles_won`+`interceptions` (no xG, no
  duels/dribbles); the *only* full defensive+possession source is StatsBomb,
  which is **intl-only** (287 players, big nations).
- So **EA's defensive sub-attributes carry the most load** (they're the prior
  for the dimensions empirical covers worst) → EA calibration matters **most
  for defence**, least for attacking (where Understat xG is strong).
- `xgBuildup`/`xgChain` are the redeemer for non-attackers: xGBuildup strips
  shooter+assister, so deep mids / ball-playing CBs get a possession-value
  signal even from attacking-only Understat.
- **The biggest *free*-data gap is defensive/possession depth for everyone,
  not dark-player rosters** — that, not Gulf leagues, is the real paid-data
  argument if we ever revisit it (parked).

## 2. Coverage as measured (S27 audit, name-based)

`_probe_coverage_audit.py` (deletable). Presence detected by hardened name
(+nation for intl), because the cross-source identity gap means `our_player_id`
reaches FBref cups but NOT Understat (disjoint id spaces — see §2a).

Per-source (of 1247): EA 815 (65%), top-5 504 (40%), cups 528 (42%),
intl 287 (23%); **any-source 920 (74%), dark 327 (26%)**.
Sources-per-player: 0→327, 1→256, 2→258, 3→262, 4→144.

Defensive-action coverage (cups|intl): **625 (50%)**; build-up-only 115.

| pos | squad | def_action | any_emp | dark |
|---|---|---|---|---|
| GK | 145 | 50 | 62 | 56 |
| DEF | 420 | 202 (48%) | 251 | 109 |
| MID | 372 | 208 (56%) | 233 | 90 |
| FWD | 310 | 165 (53%) | 194 | 72 |

Position skew is **mild** (cups patch defenders); GK is the special case
(its `def_action` metric is meaningless — GKs need save/sweep = StatsBomb GK
events + EA GK attrs → **separate attribute track**). Dark tail = AFC/Gulf
(JOR/UZB/QAT/EGY/IRN), genuine absence (AFC Asian Cup not in free data).

### 2a. Cross-source identity gap (banked, deferred to attribute-synthesis)
The same real player has **two unlinked ids** — a FBref-minted id (cups) and a
native Understat id (top-5) — and `our_player_id` points only at the FBref one.
For *coverage presence* this is fine (name-based detection). For *unified
attribute synthesis* (combining a player's xG from Understat + tackles from
cups + intl events) these identities must be **unified** — a real task,
deferred to the attribute-synthesis build, not this design.

## 3. Per-player calibration = the blend (the main operation)

Realignment (S27): there is **one per-player operation**, not a separate
group-calibration *then* shrinkage. EA is a stale (last-season), biased prior;
each player's "rating going into the WC" = EA pulled toward **their own** recent
empirical percentile, weighted by coverage. Empirical is used **exactly once**
→ no double-counting. Group/league de-bias is demoted (§3a).

**Everything is per-90, position-relative percentiles** (point 5): each counting
stat ÷ (minutes/90), minutes taken per player-match from the source's `minutes`
(StatsBomb minutes derived — see prereq), then percentiled within FWD/MID/DEF/GK.

The empirical estimate has **three components**:

### 3.1 Attacking / build-up percentile (recency-weighted form)
Sources, recency-weighted: **top-5 25-26 ≻ 24-25 ≻ Euro24/Copa24 ≻ AFCON23**.
Metrics (per-90): `goals, assists, xg, xa, xg_chain, xg_buildup, key_passes,
shots`. **WC22 is NOT here** (too old for "current form" → clutch only).

### 3.2 Defensive percentile
Sources, recency-weighted: **UCL/UEL/UECL (both seasons) ≻ Euro24/Copa24 ≻
AFCON23 ≻ WC22**. Metrics (per-90): `tackles_won, interceptions` (cups) +
tackles / interceptions / duels incl. aerials (StatsBomb events). Understat
contributes nothing here (no defensive data).

### 3.3 Clutch score (high-stakes differential)
High-stakes = cups + all intl tournaments. Two signed parts (per-90):
- **attacking clutch (+)** — high-stakes G/A (+xG/xA where available) **vs the
  player's top-5 league attacking baseline** (did they raise their level). Fed
  by WC22 + cup attack + tournament attack.
- **disciplinary (−)** — `fouls + yellow + red cards` per-90 in high-stakes
  games (composure under pressure), wherever available.
No *positive* defensive clutch — defence is carried by §3.2.

### 3.4 The blend
```
attr_dim = (1 − λ)·EA_pct  +  λ·empirical_pct_dim  +  clutch_adjustment
   dim ∈ {attacking, defensive};   λ = coverage_empirical (§4)
   EA absent AND empirical absent → position-average fallback (truly dark)
```
High coverage → trust the data; thin → fall toward EA; dark → position-average.
Empirical-Bayes in spirit (λ = the data weight).

### 3a. Group/league de-bias — demoted to optional v2
Only does work for DARK players (no empirical to blend toward); for everyone
with data the per-player blend overrides it. Optional v2 backstop for the dark
set (low priority — small teams). No granularity decision needed for v1.

### 3b. Build prerequisite — StatsBomb minutes
Understat + FBref carry `minutes`; **StatsBomb does not.** Per-90 for tournament
stats needs minutes derived per player-match from `Starting XI` +
`Substitution` events (+ period ends). Small derivation step, runs before the
percentile pipeline.

## 4. Coverage score

Two related numbers, because EA is dual-role (a "how much we know" source AND
the shrink target):
- **`coverage_total`** — dashboard "how much we know", includes EA.
- **`coverage_empirical`** = the shrinkage weight **λ** — top-5/intl/cups only;
  EA excluded (it *is* the prior). EA presence separately sets prior
  informativeness (informative vs bare position-average).

**Form: weighted noisy-OR with depth saturation** (rewards the best source,
weaker ones add diminishing redundancy, respects minutes):

```
depth dₛ = min(minutesₛ / 900, 1)     # ~10 full matches saturates; EA dₛ=1 if present
                                       # intl: matches × 90 as a minutes proxy
contribution cₛ = wₛ · dₛ
   weights (maintainer ranking, tunable): top5 1.0  intl 0.85  EA 0.50  cups 0.40

coverage_total     = 1 − Π(1 − cₛ)  over {top5, intl, EA, cups}
coverage_empirical = 1 − Π(1 − cₛ)  over {top5, intl, cups}        ← λ
```

Team coverage = **mean `coverage_total`** per nation, plus **min/median** so a
team isn't flattered by its stars.

- **Dimension-aware coverage (attacking vs defensive): v2 refinement, not v1.**
  The defensive gap is moderate (50% have def actions), so a single scalar is
  defensible to start; split attacking/defensive coverage later.
- **GKs: separate track** (own attribute set + own coverage from GK events/EA).
- **Recency: RESOLVED** — handled inside the attacking/defensive percentiles
  as ordered source weights (25-26 ≻ 24-25 ≻ 2024 tournaments ≻ AFCON23 ≻ WC22),
  not a separate decay. The clutch term also carries recent high-stakes form.

## 5. Prior + shrinkage blend

**Merged into §3.4** — the per-player blend *is* the prior/shrinkage step (one
operation, empirical used once). Clutch (§3.3) is the high-stakes mentality
modifier (cup attack + tournament attack vs league baseline, − fouls/cards).
Caveat banked: clutch is a small, *selected* sample (Europe-reaching / qualified
teams) and noisy → keep it a **modest** modifier, not a core attribute.

**[OPEN] D-blend-2:** clutch modifier functional form + cap (how big a swing it
can apply). **[OPEN] D-blend-1:** λ at dimension level (attacking vs defensive)
— already implied by §3.4's `attr_dim`; confirm at build.

## 6. Sequencing

1. Coverage audit ✅ (S27).
2. **StatsBomb minutes derivation** (§3b) — prerequisite for tournament per-90.
3. Per-90 percentile pipeline: attacking / defensive percentiles + clutch
   (§3.1–3.3), position-relative, recency-weighted.
4. Coverage score λ (§4) computed + persisted (per-player + per-nation table).
5. Per-player blend (§3.4): `(1−λ)·EA + λ·empirical + clutch` → attribute
   estimates the chessboard consumes.
6. (later) dimension-aware coverage v2, cross-source identity unification,
   sub-attribute calibration, group de-bias backstop, GK track, paid revisit.

## 7. Open knobs (close one at a time)
- **D-blend-2** clutch modifier functional form + cap (size of swing).
- Recency weight values (25-26 vs 24-25 vs tournaments) — tune on distributions.
- Coverage-score weights + 900-min saturation — tune on distributions.
- (resolved: D-cal-1 group granularity — per-player now; D-cov-1 recency — via
  source weights; D-blend-1 — dimension-level λ per §3.4.)

## References
- `analysis_pipeline_design.md`, `resolver_design.md`, `data_sourcing.md`
- xGChain/xGBuildup (build-up value): https://understat.com (per-player build-up metrics)
- Empirical-Bayes shrinkage: existing `player_season_stats.shrunk_form_eb` precedent
