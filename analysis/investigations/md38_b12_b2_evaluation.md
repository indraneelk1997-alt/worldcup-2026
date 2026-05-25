# MD38 B1.2 vs B2 Evaluation

**Date**: 2026-05-25 (S14)
**Predictions**: pre-registered 2026-05-22, tags `md38-b12-prereg` + `md38-b2-prereg`
**Actuals**: ingested via `src/load/load_md38_actuals.py` (append-only)
**Evaluation rows**: 20 in `md38_evaluation_b12_b2` (10 fixtures × 2 models)

## Aggregate results

| Metric (lower = better) | B1.2 | B2 | Delta (B2 − B1.2) |
|---|---|---|---|
| Total log-loss scoreline | 27.488 | 27.343 | **−0.145** |
| Total log-loss outcome | 12.209 | 12.203 | **−0.006** |
| Total Brier (H/D/A) | 7.502 | 7.471 | **−0.031** |

B2 wins on all three metrics by small margins. The wins are **directionally consistent with Saturday's calibration** (which predicted ~+0.026 average log-likelihood improvement per match, ≈ +0.26 across 10 matches; observed +0.145).

## Where the B2 advantage came from

The τ correction modifies only the four low-score cells (0,0), (0,1), (1,0), (1,1). For the 6 MD38 fixtures with actual scorelines outside those cells, B2 and B1.2 assigned **identical** scoreline probabilities (delta = 0.000 on log-loss scoreline). The entire B2 advantage on this metric came from three actual 1-1 draws:

- Burnley 1-1 Wolves: delta −0.0858
- Liverpool 1-1 Brentford: delta −0.0858
- Nottingham Forest 1-1 Bournemouth: delta −0.0858

The three deltas are nearly identical because the τ multiplier at (1,1) is structural (`1 − ρ = 1.0896`). One actual 1-0 (Tottenham-Everton) cost B2 +0.1122 — the symmetric loss. **The mechanism is operating exactly as designed.**

No actual 0-0 or 0-1 scorelines occurred on this slate, so two of the four corrected cells weren't sampled.

## What this is and isn't

**Is**: a clean pre-registered comparison verifying that B2 produces the *direction* of effect Saturday's calibration predicted. Sample mechanism is verified.

**Isn't**: a confirmation of B2's practical value. n=10 is too small to distinguish "B2 is genuinely better" from "B2 happened to be better on this matchday." The −0.145 log-likelihood advantage is roughly the magnitude expected from a single matchday and would be swamped by ordinary variance.

## What both models got wrong

Both models had a Brier score of ~0.75. A no-skill baseline (always predict league base rates ≈ (0.46, 0.24, 0.30)) would score around 0.60 Brier. **Both models underperformed an uninformed baseline on this slate** — a finding worth flagging.

The Man City 1-2 Aston Villa upset alone contributed 14.6% of B1.2's total outcome log-loss (model said P(home win) = 63.5%). The model has no mechanism to know that:

- City had nothing to play for (title secured weeks ago)
- The World Cup is two weeks away
- Manager rotation patterns on MD38 differ systematically from MD1–37

This is a **bigger lever than independence-vs-DC**: the team-strength inputs are stale-by-design for any match where in-season context (rotation, motivation, schedule density) deviates from the seasonal average.

## Carry-forward

1. **B2 ships as a usable model** but with the honest caveat that its measured advantage over B1.2 on real out-of-sample data is small and within plausible noise. Ranks among `model_version`s in the same prediction tables; no demotion needed.
2. **The bigger modeling gap is context-aware strength**, not within-Poisson corrections. This is a V1.04 design conversation.
3. **MD38-specifically** is a poor evaluation slate — high non-modellable variance. Future evaluations should accumulate across many matchdays, not lean on single high-stakes endpoints.

## Files & data references

- Predictions: `md38_predictions_b12` and `md38_score_grid_b12`, model_versions `B1.2_v103_poisson_indep` and `B2_v103_dc_post_hoc`
- Actuals: 10 new rows in `games`, 20 in `team_match_stats`, 312 in `player_match_stats`, all with `season = '2025-2026'` and `match_date = '2026-05-24'`
- Evaluation: 20 rows in `md38_evaluation_b12_b2`
- Scripts: `src/load/load_md38_actuals.py`, `src/load/create_md38_evaluation_table.py`, `src/simulate/evaluate_md38_predictions.py`
- Calibration parameter: `model_parameters_v103` row with `parameter_name='dc_rho'`, `value=−0.089590`