# Team Playstyle — Empirical Leg (Decision 2) — Design

> Designed S31 (2026-06-12), observe-driven. Covers **only** the empirical
> leg of D2. The hand prior and the blend (`axis = (1−λ_team)·prior +
> λ_team·empirical`) live in `chessboard_design.md` (D2). Companion build:
> `derive_team_playstyle_empirical.py` (not yet written).

## Purpose

Derive a 5-axis tactical-style vector per **national team per tournament**
from StatsBomb open event data (the only source where our players appear in
*national-team* matches, unlike our club data). Four tournaments:

| tournament | competition_id | season_id | matches | teams |
|---|---|---|---|---|
| World Cup 2022 | 43 | 106 | 64 | 32 |
| Euro 2024 | 55 | 282 | 51 | 24 |
| AFCON 2023 | 1267 | 107 | 52 | 24 |
| Copa América 2024 | 223 | 282 | 32 | 16 |

→ **96 team-tournament rows** is the empirical pool.

## Coordinate convention — CONFIRMED empirically (not assumed)

StatsBomb normalises **every event to the acting team attacking left→right**:
own goal `x=0`, opponent goal `x=120`; pitch `120×80`. **No halftime flip**,
and the two teams in a match are *not* mirror images — each lives in its own
attacking frame.

Verified by probe (rule 3), three independent angles:
- **Period split** of defensive-action `x` — Georgia P1 39.0 / P2 44.5. A
  physical (un-normalised) frame would mirror the halves (≈39 / 81) and pool
  to ~60; instead both halves sit low. Decisive. (Germany 60.0/60.2 is
  consistent but uninformative — mirror and normalised coincide at the
  midpoint.)
- **Per-match stability** — Spain's per-match defensive means all 55–76; no
  match jumps frame.
- **Same-match check** — Germany 67 / Scotland 45 reflect territorial
  dominance in a 5–1, not a mirror (would sum to 120).

**Consequence:** per-team `x` aggregation is valid as-is; no per-period
correction. Corroborating spec: StatsBomb Open Data Specification,
<https://github.com/statsbomb/open-data>.

## The five axes — v1 metric definitions

Each metric is computed per (team, tournament) from `statsbomb_event` typed
columns (`x, end_x, y, type, position`), then normalised (see below). All
oriented so **1 = the high end** of the axis label.

| # | Axis | v1 metric | Notes / source cols |
|---|---|---|---|
| 1 | **Directness** | median pass distance `√(Δx²+Δy²)` **+** share forward (`end_x > x`), combined post-normalisation | `x,y,end_x,end_y`; type=`Pass` |
| 2 | **Width** | share of passes + carries **starting** in wing channels (`y ≤ 18 or y ≥ 62`), **attacking half only** (`x ≥ 60`) | `x,y`; type ∈ `Pass,Carry` |
| 3 | **Line height** | **median `x` of back-line players' defensive engagements** | see below |
| 4 | **Press** | **PPDA** — opp completed passes ÷ team defensive actions in the pressing 60% | pinned + cited, see Axis 4 below |
| 5 | **Possession** | team pass-share in its matches (`team passes / all passes`) | type=`Pass` |

### Axis 3 — line height, the careful one

Defensive *engagements* are made by the whole team, so the median over **all
players measures team engagement/press height, not the back line** — it runs
10–17 units high, and the gap is team-dependent (forwards who press higher
inflate it more). Measured S31:

| team | DEF_line (CB/FB/WB) | DM | ALL | MID_FWD |
|---|---|---|---|---|
| Spain | **49.0** | 59.0 | 65.6 | 77.8 |
| Germany | **47.3** | 53.9 | 58.7 | 72.4 |
| Georgia | **22.7** | 34.3 | 33.1 | 43.1 |

So line height isolates the **back line only** — `position` containing the
substring `"Back"` (Center Back, L/R Back, L/R Wing Back); DM and GK excluded.
Sample is healthy (300–470 actions/team-tournament). Reputation-aligned
(Spain ≳ Germany ≫ Georgia).

**Engagement-set** (excludes deep last-ditch events that would drag the median
toward our own goal): `Pressure, Ball Recovery, Duel, Interception,
Dribbled Past, 50/50`. **Excluded:** `Clearance, Block`.

Why **median, not mean or mode**: mean is dragged low by deep clearances;
the modal 5 m bin is unstable because these distributions are broad plateaus
(Spain's modal bin = 92.5 vs median 65.6 — a 27-unit artefact). Median over
the filtered, back-line-only set is the robust estimator.

### Axis 4 — PPDA (pinned + cited, S31)

Definition (StatsBomb's own, corroborated by the Premier League):
**PPDA = opponent completed passes in their own 60% ÷ the pressing team's
defensive actions in that same 60%.** Lower = more intense press. Sources:
<https://support.hudl.com/s/article/passes-defensive-action>,
<https://www.premierleague.com/en/news/4250153/passes-per-defensive-action-explained>.

Mapped to our event vocab + normalised frame (each team attacks +x, length 120):

- **Denominator** — team's actions with `x ≥ 48` (outside own defending 40%)
  and `type ∈ ('Interception','Foul Committed','Block','Dribbled Past')`
  **OR** (`type='Duel'` **AND** `raw.duel.type.name='Tackle'`).
  *Duel must be tackle-filtered* — confirmed S31 that `Duel` is ~50%
  `Aerial Lost` (6195) vs `Tackle` (6618); raw `Duel` would distort the press
  signal. `Pressure` and `Ball Recovery` are deliberately **not** in PPDA.
- **Numerator** — the opponent's **completed** passes (`outcome IS NULL` —
  confirmed encoding; failures carry `Incomplete/Out/Unknown/Pass Offside`)
  with `x ≤ 72` (opponent's own 60%, in the opponent frame).
- Both thresholds describe the **same physical strip** (the 60% nearest the
  building team's goal). Computed by pairing each `match_id`'s two teams
  (a team's opponent = the other team in that match).
- `ppda_norm` = percentile-rank **inverted** so 1 = most intense press.

## Grain + normalisation

- **Grain:** one row per `(team, competition_id, season_id)`. Keep tournaments
  separate so recency-weighting (2024 ≻ WC22) and `λ_team` confidence stay a
  clean **downstream** step — don't pre-average across coach eras.
- **Normalisation:** per-metric **percentile-rank across the 96-row pool** →
  `[0,1]`. Robust to outliers vs min-max; min-max noted as the alternative.

## Proposed table — `team_playstyle_empirical`

Wide (one row = one team-tournament style vector) — the natural shape for a
vector consumed as a unit, and small (96×~12). Store **both raw and
normalised** for auditability. Long is the alternative (maintainer's standing
preference for large data) but unwarranted at this size.

```
team_playstyle_empirical
  team                VARCHAR     -- StatsBomb team name (NOT yet mapped to 2026 nation)
  team_id             INTEGER     -- StatsBomb team_id
  competition_id      INTEGER
  season_id           INTEGER
  n_matches           INTEGER     -- sample size (feeds λ_team confidence)
  directness_raw      DOUBLE
  width_raw           DOUBLE
  line_height_raw     DOUBLE
  ppda_raw            DOUBLE
  possession_raw      DOUBLE
  directness_norm     DOUBLE      -- percentile-rank 0–1
  width_norm          DOUBLE
  line_height_norm    DOUBLE
  ppda_norm           DOUBLE      -- inverted so 1 = most intense press
  possession_norm     DOUBLE
  model_version       VARCHAR
  created_at          TIMESTAMP
  -- PK (team_id, competition_id, season_id)
```

Self-contained on StatsBomb's ID space → no FK links into our tables → no
FK-block exposure. DERIVED → `--apply` = wholesale `CREATE OR REPLACE` rebuild.

## Confounds & limitations (banked)

- **Game-state.** Line height drops when protecting a lead (Spain 69→57
  H1→H2). v1 pools all minutes; **v2** could restrict to level game-state /
  first half to recover *intended* line height.
- **Sample size.** Group-stage exits = ~3 matches → noisier estimates. Feeds
  `λ_team` (don't over-trust thin samples).
- **PPDA pinned** (see Axis 4). v1 simplification banked: completed-vs-all
  passes barely moves the ranking post-normalisation; we follow the StatsBomb
  glossary (completed) for source-fidelity.
- **Team → 2026 nation mapping** is a separate downstream join. Not all
  StatsBomb teams are 2026 qualifiers; the dark AFC/Gulf set has **no**
  StatsBomb data → pure prior (by design).

## Open / v2

- Directness: add possession-to-shot speed (passes/duration from possession
  start to shot).
- Width: pass-**angle** lateral test as a cross-check (`pass.angle` in `raw`).
- Press: secondary **press-height** signal = `MID_FWD` engagement-x
  (Spain 77.8 vs Georgia 43.1) corroborating PPDA.
- Line height: CB-only variant if full-backs ever look inflationary.
- Game-state weighting (above).
