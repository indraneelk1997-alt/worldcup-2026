# B1.2 Strength Formula
The B1.2 team xG prediction model: design, calibration, and findings.
Shipped in Session 12 of V1.03. Replaces V1.03's original strength formula
(sum of starter ratings), which overpredicted team xG by ~1.0 per match
because it ignored the opponent.

This is the first of several V1.03 component docs. A master `V1.03
METHODOLOGY.md` aggregating all V1.03 changes is deferred.

---

## Goal

Predict expected goals (xG) for a single team in a single match, given
the two teams' identities, the season, and which side is home.

The V1.03 formula before this redesign was effectively:

    xG_team = sum(rating × minutes_fraction over starting XI)

It had no opponent term. Residual diagnosis in Session 11 (see
`analysis/investigations/investigate_residuals_v103.py`) showed:

- Mean residual = -0.990 xG (predicted overshoots actual by ~1.0)
- Opponent xG-allowed: 0.72 xG residual spread across quintiles
- Opponent attack strength: 0.61 spread
- Opponent PPDA (pressing): 0.38 spread
- Strong-vs-strong matchups systematically overpredicted (predicted 3-4,
  actual 1)
- Aston Villa anomaly (S9): resolved as missing-features problem, not a
  math floor in the formula

The opponent had to enter the formula structurally, not as an additive
correction.

## Pipeline
team_match_stats (1500 team-matches, long format from per-match ingest)
│
├── load_team_season_strength_v103.py
│       ├── team_season_strength_v103
│       │   (per-team-per-season: avg_xg_for, avg_xg_allowed, avg_ppda_pressing)
│       └── league_averages_v103
│           (per-season + GLOBAL row: league_avg_xg, league_avg_ppda)
│
└── calibrate_b12_v103.py
└── Joint MSE grid search over (alpha, home_mult, away_mult)
→ optimum: alpha=0.00, home_mult=1.05, away_mult=0.90
predict_xg_v103.py
└── predict_xg(home_team, away_team, season)
→ XgPrediction(xg_home, xg_away, + diagnostics)
load_team_match_predictions_b12.py
└── team_match_predictions_b12 (1500 predictions, model_version='B1.2_v103')

## The formula
xG_team = (own_avg_xg_for * opp_avg_xg_allowed / league_avg_xg)
* side_multiplier

Where:

- `own_avg_xg_for` = predicting team's mean xG scored per match, from
  team_season_strength_v103 for the relevant season.
- `opp_avg_xg_allowed` = opponent's mean xG conceded per match, same source.
- `league_avg_xg` = league mean xG per team-match for the relevant season,
  from league_averages_v103. Per-season, not global — small environment
  shift between 2024-25 (1.601) and 2025-26 (1.523) is preserved.
- `side_multiplier` = `home_multiplier` if predicting team is home,
  else `away_multiplier`. Calibrated values: 1.05 home, 0.90 away.

Three parameters total: the two side multipliers, plus the league average
(structural normalizer, not optimized).

This is the Pythagorean / SPI structure used by Dixon-Coles (1997) and
FiveThirtyEight's SPI for football. Multiplicative ratios mean
strong-vs-strong matchups partially cancel — the failure mode of the
original additive formula.

## Design rationale

### Why multiplicative, not additive

Two structures were considered:

- **Additive linear:** `xG = β0 + β1·own_attack + β2·opp_def + ...`
  Interpretable, easy to fit. But the failure mode of the original
  formula was *exactly* "strong attack added to weak defense produces
  4+ xG predictions when actuals are 1". Linear structures perpetuate
  this. The Aston Villa 0.22 floor problem from S9 was a linear-model
  artifact.

- **Multiplicative (chosen):** `xG = attack × opp_def / league_avg × ...`
  When both teams are above average, the multipliers partially cancel.
  Matches Dixon-Coles convention for football goals. Less linearly
  interpretable but doesn't blow up at the extremes.

Additive remains parked as a possible V1.04 comparison.

### Why team-level averages, not XI-based

The original V1.03 formula used the actual starting XI (sum of rating ×
minutes). B1.2 uses team-level season averages. Two reasons:

1. The residual investigation showed the bias was dominated by *opponent*
   features, not XI variation. Season averages are sufficient to fix the
   structural problem.
2. Using XI-based predictions for the simulation step is a separate
   concern (lineup quality scaling, sub effects). Conflating "team
   identity" with "tonight's lineup" made the original formula hard to
   debug.

A future model could modulate `own_avg_xg_for` by a "lineup quality
ratio" — i.e., how full-strength tonight's XI is vs the season-average
lineup. Parked.

### What about pressing (PPDA)?

A pressing term was included in the original B1.2 design:
xG_team = (...) * (opp_avg_ppda / league_avg_ppda) ** alpha

The hypothesis was that a high-pressing opponent (low PPDA) should
reduce the predicting team's xG. The S11 residual investigation
supported this — PPDA quintiles showed 0.38 xG residual spread.

**Calibration disproved the hypothesis in this functional form.**
Joint MSE grid search over (alpha, home_mult, away_mult) returned
optimal alpha = 0.00 — the pressing multiplier converges to 1.0,
contributing nothing.

Two explanations were considered:

1. *PPDA's signal is absorbed by opp_avg_xg_allowed.* The two features
   correlate at r=0.53 across team-seasons. Teams that press well also
   concede fewer xG. In the multiplicative form, the optimizer picks one.
2. *The pressing form is mis-specified.* Maybe pressing is an
   interaction (matters more vs strong attacks), or additive, or
   asymmetric.

The B1.2 residual diagnosis (analysis/investigations/
investigate_residuals_b12.py) decided between them: with alpha=0, the
new residuals showed **0.026 xG spread across PPDA quintiles** —
essentially zero, an order of magnitude below the 0.2 threshold for
declaring residual structure.

Conclusion: PPDA's signal is fully absorbed by opp_avg_xg_allowed in the
multiplicative form. The term was removed from the formula entirely.

This was the headline empirical finding of Session 12 — a feature we
included on principled grounds turned out to add no marginal information
once a related feature was in the model multiplicatively.

## Calibration

### Method

`src/model/calibrate_b12_v103.py` runs a joint grid search over:

- `alpha ∈ [0.0, 0.1, ..., 1.5]` (16 values) — pressing exponent
- `home_multiplier ∈ [0.90, 0.95, ..., 1.30]` (9 values)
- `away_multiplier ∈ [0.70, 0.75, ..., 1.10]` (9 values)

Total: 1296 grid points × 1500 team-matches = ~1.9M predictions. Loss
function is MSE of (predicted − actual). Vectorized over the feature
table for speed (~seconds, vs hours in the initial unvectorized
implementation).

### Result

Optimum:

- `alpha = 0.00` → pressing term dropped from formula
- `home_multiplier = 1.05`
- `away_multiplier = 0.90`
- MSE = 0.5943
- Mean residual = -0.036 (from V1.03's -0.990)

The loss surface is a flat valley near the optimum — top 10 grid points
all sit at MSE 0.594-0.598, spanning small ranges of all three
parameters. The exact values shouldn't be treated as precise; ±0.05 on
the multipliers is within noise.

Home/away multipliers don't sum to 2 (sum = 1.95). Home advantage is
modeled as moderate — ~15% predicted-xG uplift for home teams. Roughly
consistent with the football-literature consensus of ~0.3 goals of home
advantage.

## Validation: V1.03 vs B1.2

| metric | V1.03 | B1.2 |
|---|---|---|
| Mean residual | -0.990 | -0.036 |
| SD residual | 0.850 | 0.770 |
| Pearson r (pred, actual) | 0.407 | 0.528 |
| Opp xg_allowed residual spread | 0.717 | 0.029 |
| Opp xg_attack residual spread | 0.607 | 0.038 |
| Opp PPDA residual spread | 0.375 | 0.026 |
| Predicted_xg quintile spread (saturation) | 0.563 | 0.085 |

All moderators flatten by 5-25×. Saturation effect (residuals worsening
in higher predicted-xG buckets) is largely resolved as a side effect of
multiplicative structure — the parked B1 saturating-curve approach
proved unnecessary.

The Pearson r improvement from 0.407 to 0.528 is meaningful but should
be treated as an upper bound: season-mean features include the match
being predicted (small leakage, ~1/38 contamination per match).

## Known limitations

- **Leakage in calibration.** Team averages used to predict match M
  include M itself. Effect is small (1/38 per match) but biases fit
  toward looking better than out-of-sample. Mitigation deferred to V1.04
  — options are leave-one-out averaging or train/test split.

- **No time-awareness.** Season averages are used flat — early-season
  predictions use late-season data. A team's strength is treated as
  fixed across the year. Form, injuries, manager changes don't enter.
  Worth revisiting for V1.04 via expanding-window averages.

- **Southampton-style anomalies.** Teams with high variance in xG
  conceded (Southampton 2024-25 ranged from <1 to >5 xG conceded in
  different matches) produce equal-and-opposite residuals across their
  schedule. Half of B1.2's top/bottom 8 outlier residuals are
  Southampton matches. Fundamental limit of using season means as
  features.

- **No per-match features.** Lineup changes, rest days, recent xG form,
  competition stage — none enter. Each team's "strength" is one number
  per season. Adding these features is the natural next class of model
  improvements.

- **EPL-only.** All calibration is on Premier League data. Whether 1.05
  / 0.90 are right multipliers for international football (WC26 context)
  is untested. Likely close but not validated.

- **PPDA dropped, not refuted.** The S12 finding was that pressing's
  multiplicative form contributes nothing once opp_xg_allowed is in the
  model. An additive or interaction-based pressing term might still
  carry signal. Not pursued in B1.2.

## Files

- `src/load/load_team_season_strength_v103.py` — populates feature tables
- `src/model/predict_xg_v103.py` — prediction function
- `src/model/calibrate_b12_v103.py` — joint grid search calibration
- `src/load/load_team_match_predictions_b12.py` — predictions table loader
- `analysis/investigations/investigate_residuals_b12.py` — validation diagnostic

Tables created:
- `team_season_strength_v103`
- `league_averages_v103`
- `team_match_predictions_b12` (model_version='B1.2_v103')

## References

- Dixon, M. and Coles, S. (1997). "Modelling association football scores
  and inefficiencies in the football betting market."
  https://www.math.ku.dk/~rolf/teaching/thesis/DixonColes.pdf
- FiveThirtyEight Soccer Power Index methodology:
  https://fivethirtyeight.com/methodology/how-our-club-soccer-predictions-work/
- Statsbomb PPDA definition (used here for the pressing-feature
  semantics): https://statsbomb.com/articles/soccer/explaining-and-translating-statsbomb-data-glossary-ppda/