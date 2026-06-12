# Blend redesign — EA↔empirical λ re-tune (S28)

**Status:** LOCKED S28 (2026-06-12). Supersedes the flat per-dimension λ caps
from the S27 as-built engine (`coverage_prior_design.md` §8). No new engine
structure — this is a re-tune of three numbers plus an honest reframe of what
they mean. Companion to `coverage_prior_design.md` (the spine) and
`_probe_adjusted_ratings.py` (the engine these values live in).

---

## The engine (unchanged shape)

Per dimension `d ∈ {Attack, Possession, Defense}`, all as percentiles within
`primary_position_group` (GK excluded — separate track):

```
adj_pct_d = (1 − λ_d)·EA_role_pct_d + λ_d·empirical_pct_d
λ_d       = min(minutes_d / 900, 1) · CAP_d
no empirical → λ=0 (pure prior);  no EA → empirical only.
```

## What changed (Decision 1+2)

### 1. λ reframed: minutes-cap → confidence
The old `CAP_d` was treated as "max empirical weight." We reframe it as a
**per-dimension confidence** — *how much the empirical signal deserves to
override the prior for this dimension*. Nothing in the code changed; CAP was
always the only per-dimension knob. The reframe just makes us choose its value
on signal-reliability grounds rather than as an abstract ceiling.

### 2. The blend stays SYMMETRIC — no asymmetry, no clamp
We considered making the adjustment asymmetric (resist pulling a high-EA player
*down* when empirical confidence is low — the "don't punish Van Dijk for not
racking up tackles" rule). **Rejected**, because:
- Asymmetry bakes in *"trust EA about elites"* — which is the exact prior bias
  this whole pipeline exists to calibrate away. A genuinely-declined defender
  posting a real low signal would be shielded by his stale EA score.
- A symmetric blend with an honest **low** CAP already gives a *naturally
  bounded* correction: the maximum swing is `CAP·100` percentile points. For
  Defense (CAP 0.25) that's a ±25-pt ceiling — gentle by construction, in both
  directions, with no special-casing.

So the low CAP *is* the clamp. Symmetric stays.

### 3. The locked values

| dim | CAP (was → now) | empirical source | why |
|---|---|---|---|
| Attack | 0.80 → **0.60** | Understat `(goals+xa)/90` | cleanest signal we have, but still only a *nudge* on the complete EA attribute set |
| Possession | 0.80 → **0.50** | Understat `(key_passes+xg_buildup+xg_chain)/90` | good but team-style-inflated (xg_chain borrows teammate value) → half weight |
| Defense | 0.50 → **0.25** | FBref cups `(tackles_won+interceptions)`, padj+suppression | weakest proxy: no duels, no xG, counting-stat trap on elite CBs → small say |

**The ordering is the point.** At full minutes the empirical weight is
Attack 60% · Possession 50% · Defense 25% — exactly the data-reliability
ordering from `coverage_prior_design.md` §1 ("attacking well-served; defence is
the club-football hole"). The CAP vector *encodes* that finding; it is not a set
of free parameters.

## Evidence it works (S28 sweep, `_probe_adjusted_ratings.py`)

Symmetric blend, real squad, percentiles within position group:

| case | adj @ old (.8/.8/.5) | adj @ locked (.6/.5/.25) |
|---|---|---|
| Van Dijk — Defense | 69 (too harsh) | **85** (fair) |
| Timber — Attack | 23 | 40 |
| Veiga — Attack | 21 | 38 |
| Bentancur — Possession | 25 | 45 |
| Ouedraogo — Attack (young overperformer) | 83 (spike) | 67 (tempered) |

Stars hold sensibly: Salah 97/95/71, De Bruyne 80/98/81, Bellingham 96/92/81,
Haaland 97/50/60, Van Dijk 80/67/85 (Attack/Possession/Defense).

### Residuals this also helped (from §8 "known residuals")
- Elite-CB defense over-correction → fixed (Van Dijk 69→85).
- Small-sample young-overperformer spikes → tempered (lower CAP holds them
  nearer the EA prior; Ouedraogo 83→67).

### Residuals still open (not addressed here)
- StatsBomb per-match stats, clutch term, recency weighting — not yet folded in.
- Cross-source identity unification (FBref/Understat split ids) — deferred.
- The CAP values are tuned on eyeballed face-validity, not a held-out metric;
  revisit if/when we have ground truth to score against.

## How to change these later
CAP defaults live in `_probe_adjusted_ratings.py`. Override per-run without
editing:
```
CAP_ATT=0.7 CAP_POSS=0.6 CAP_DEF=0.3 uv run python src/load/v2_ingest/_probe_adjusted_ratings.py
```

## Attribute-level mapping (LOCKED S28)

The engine outputs three *dimension* percentiles, but the chessboard consumes
*individual sub-attributes* (`analysis_pipeline_design.md` zone-battles read
pace/dribbling/tackling/finishing directly). So a dimension's form percentile
must map **down onto its constituent EA sub-attributes**. This replaces the
earlier "overall combination" idea — there is no single overall number; the sim
reads adjusted attributes.

**Decision: uniform additive shift of the discriminator attributes only.**

```
δ_d        = adj_rating_d − raw_EA_rating_d          # form correction, EA points
adj_attr_i = raw_EA_attr_i + s_d   for each base/discriminator attr i of dim d
             (bonus buckets — Skills, IQ, Physical incl. pace/strength/agility —
              left at raw EA value)
```
where `adj_rating_d` is `adj_pct_d` inverted against the position group's EA
dimension-rating distribution (the exact inverse of how `ea_pct_d` was formed),
and `s_d` is the per-attribute shift that realises `δ_d` (see impl note).

Discriminator sets (from `_ea_attribute_buckets.py`):
- **Attack**: finishing, shot_power, long_shots, penalties, heading_accuracy
- **Possession**: short_pass, long_pass, crossing, ball_control, vision
- **Defense**: def_awareness, standing_tackle, sliding_tackle, interceptions

**Why uniform, why discriminators only:**
1. **Signal is dimension-aggregate.** We know a player's *attacking output*
   percentile, not whether his long-shots vs penalties moved → no basis to
   redistribute *within* a dimension. Uniform is the only shape that invents no
   attribute-level information. Proportional/scaled would fabricate texture.
2. **Form is output, not athleticism.** More goals ≠ more pace. Physical/IQ/Skill
   buckets stay at EA value (also EA's *most reliable* data — athleticism is the
   least subjective thing EA rates).
3. **Base attributes are role-exclusive** → `δ_Attack` and `δ_Possession` never
   fight over a shared attribute (bonus attributes are shared; another reason to
   leave them alone).

**Coherence:** the chessboard leans on pace + dribbling — exactly the athletic
attributes we leave untouched — so the sim gets athletic inputs straight from
trustworthy EA, and our form correction refines only output attributes
(finishing/tackling/passing). Clean division of labour.

**Boundary accepted:** form *never* touches Physical/IQ/Skill ratings, even for a
player whose whole game visibly changed. (Maintainer confirmed S28.)

### Off-role gate — Option A (LOCKED S28, prototype-driven)
The first attribute prototype surfaced that the **largest** shifts were landing on
*off-role* dimensions — a CB's Attack (−13 to shot_power, driven by set-piece-noise
goals+xa) and a playmaker's Defense (−13, from noisy cup tackles). CAP is global
per dimension, so it can't tell a striker's attacking signal (real) from a CB's
(noise). Fix: **gate which dimensions get blended by position group**; off-role
dims keep `λ=0` (pure EA prior, zero attribute shift).

```
RELEVANT = { DEF: {Possession, Defense},   # no trustworthy attacking signal
             MID: {Attack, Possession, Defense},   # pivots/box-to-box: all three
             FWD: {Attack, Possession} }    # no trustworthy defensive signal
```
(MID excludes CAMs/wingers — those are grouped FWD.) **Accepted cost:** a forward's
pressing and a centre-back's set-piece threat never receive an empirical bump.
Implemented in `_probe_adjusted_ratings.build()` as a `λ→0` mask.

### Impl note — to resolve by observation when prototyping
`role = 0.75·base + 0.25·weighted_bonus` (from `_ea_attribute_buckets.py`). Since
we shift only the *base* discriminators and leave bonus fixed, a uniform shift `s`
on each discriminator moves `base` by `s` and `role` by `0.75·s`. So to realise a
role-level `δ_d`, `s_d = δ_d / 0.75` — **but** confirm against real numbers
whether we want the target defined on the role composite or on the base alone,
and clamp adjusted attributes to [1, 99]. Settle this in the prototype, not from
memory (S14 lesson).
