# Chessboard Item 4 — Playstyle-Axis → Kernel Transforms (the SHIFT leg)

> Implements/refines **D5** in `chessboard_design.md`. This is the SHIFT in
> `final = BASE(formation) ⊕ SHIFT(team playstyle) ⊕ TWEAK(player playstyle)`.
> Designed S33; not yet coded. Read `chessboard_design.md` D1–D7 for context.

## Scope & shape (decision B, S33)

Item 4 is a **pure function**, NOT a materialised table. It fires at
**formation-assembly time** in the dashboard, once the user has picked
formation + XI + playstyles. Nothing is persisted per-nation up front; a
default-formation-per-team is a later convenience layer on top, not baked in.

**Inputs:** `occupancy_base` (the two empirical phase kernels per
`position_code`), a team's 5 blended axes from `team_playstyle_blended`
(`directness, width, line_height, press, possession`, each a percentile in
[0,1], 0.5 = median team).
**Output:** one transformed 30-cell occupancy kernel per player slot, budget
= 1.0, ready for the lateral-fan step and the battle layer.

## Coordinate recap (verified S32/S33 from `occupancy_base`)

- `zone_id = band·5 + lane`. **band** 0–5 (0 = own box … 5 = opp box).
  **lane** 0–4 (0 = LW, 1 = LH, 2 = C, 3 = RH, 4 = RW).
- `weight` = per-zone occupancy share; sums to **1.0** per `(code, phase)`
  (verified `def_wsum = 1.0` for all 22 codes).
- Two phases per code: `attack` (on-ball events) and `defence` (defensive
  actions). 22 outfield codes; GK is a separate track.

## The transforms

### 4.1 possession — phase blend (the outermost op)
A team's occupancy over a match is a time-blend of its attack-phase and
defence-phase positions, weighted by how much it has the ball:

```
occ = p · attack_kernel' + (1 − p) · defence_kernel'
```

`p = possession` axis (v1: used directly as the blend weight; monotonic remap
to a literal possession share is a tunable for later). The two kernels are the
*already-transformed* attack'/defence' from the legs below.

### 4.2 line_height — vertical (band) translate, BOTH phases
Sets where the whole block sits. Anchored on the back line (this is literally
how the axis was measured in S31: median x of back-line defensive engagements).

```
line_shift = LINE_GAIN · (line_height − 0.5)        # bands; ± around the empirical mean
band ← band + line_shift                            # applied to every cell, both phases
```

### 4.3 press — front-role push, DEFENCE phase only (refined S33)
Press is an out-of-possession behaviour → warps the **defence kernel only**.
It is **not** a uniform shove: front roles (FW/MID) close down high, the back
line does not move. That is guaranteed for free by the empirical `forwardness`
vector below (CB → 0.0).

```
press_push = PRESS_GAIN · (press − 0.5)             # bands at forwardness = 1
band ← band + press_push · forwardness(code)        # defence kernel cells only
```

**Compression is emergent — NO separate compaction term (locked S33).**
With the back fixed by `line_shift` and the front pushed by `press_push`:

```
block_length ≈ 2.74 + press_push − line_shift
```

A high line *shortens* the block (back pulled up toward front); high press
*lengthens* it (front pushed away). A Bielsa-type side (high press **and** high
line) stays compact because the two terms partly cancel — exactly "press
combined with line height decide compression." An explicit compaction scalar
would double-count `line_height`.

### 4.4 width — lateral stretch + lane bias (resolves LM/RM)
Sets how wide the team plays. Center lane (2) is the pivot; cells move
outward (toward 0/4) when wide, inward (toward half-spaces) when narrow,
scaled by distance from center so wide players move most:

```
lane_shift = WIDTH_GAIN · (width − 0.5) · sign(lane − 2) · |lane − 2|
lane ← lane + lane_shift                             # both phases
```

**LM/RM resolution:** these codes are flagged context-dependent in D3. Width
drives it — under high width they sit wide (winger-like, lanes 0/4); under low
width they tuck toward the half-space (CM-like, lanes 1/3). The lane_shift
above already produces this from their base position; no special-case code.

### 4.5 directness — battle-layer, no static effect
Directness is mostly **tempo/verticality in the battle resolution (item 8)**,
not a static occupancy change. Item 4 leaves the kernel untouched on this axis.

## forwardness vector (empirical, derived from `occupancy_base`)

`forwardness(code)` = min-max normalisation of each code's **defence-phase
occupancy-weighted centroid band** across the 22 codes (min = CB 0.844,
max = FW 3.612, range 2.768). **Computed at load from `occupancy_base`** (single
source of truth — don't hand-copy). Current v1 snapshot:

| code | forwardness | code | forwardness |
|---|---|---|---|
| FW | 1.000 | CM | 0.533 |
| ST | 0.991 | MF | 0.452 |
| LAM / RAM | 0.847 | DM | 0.374 |
| CAM | 0.743 | LWB / RWB | 0.285 |
| LW / RW | 0.694 | LB / RB | 0.254 |
| LM / RM | 0.568 | LCB / RCB | 0.052 |
| LCM / RCM | 0.563 | CB / DF | 0.000 |

## Composition order (per player slot)

1. Take the code's `attack` and `defence` kernels from `occupancy_base`.
2. Apply **line translate** (4.2) + **width stretch** (4.4) to **both**.
3. Apply **press push** (4.3) to the **defence** kernel additionally.
4. **Blend** by possession `p` (4.1) → one kernel.
5. **Clip** off-grid mass to the edge bands/lanes ([0,5] band, [0,4] lane) and
   **renormalise to budget 1.0** (translations push mass past the box edges;
   accumulate at the boundary rather than discard).

## Tunable constants (defaults; calibrate vs StatsBomb spatial truth)

Externalise to `data/config/kernel_transforms.json` (env-overridable, same
pattern as the blend tunables). **Locked S33** (still calibratable vs StatsBomb):

- `LINE_GAIN = 2.0`  → ±1.0 band (±20 m) at axis extremes
- `PRESS_GAIN = 2.0` → front role (forwardness 1) moves ±1.0 band (±20 m) at press extremes
- `WIDTH_GAIN = 1.0` → wing lane (|lane−2| = 2) moves ±1.0 lane (±16 m) at extremes
- possession `p` = axis value, no remap (v1)

These are **priors to validate**, not asserted truth (rule 3). The width
lane-bias function (4.4) is the piece most in need of StatsBomb calibration.

## Open / v2

- Per-phase line treatment (a high line in possession may differ from out of
  possession) — v1 translates both equally.
- possession → literal-share remap curve.
- Spread-narrowing under extreme press (if validation shows blocks too long).
- directness tempo formalised in item 8 (battle resolution).
