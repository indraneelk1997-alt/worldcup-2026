# Known Limitations

A running log of data and methodology limitations we've identified
and consciously accepted, with the version they were noted in and
the plan (if any) for addressing them.

---

## V1.01

### Mid-season transfers are not split per club
**What:** Understat (via `soccerdata`) returns a player's season stats
under their **most recent EPL club only**, with minutes/matches counted
from when they joined that club. Pre-transfer stats from their previous
EPL club are not included.

**Evidence:** Marcus Rashford (Man Utd → Aston Villa, Feb 2025) appears
in our 2024-25 data with 1435 minutes at Aston Villa only. His ~830
minutes at Man Utd earlier in the season are missing entirely.

**Impact:** Affects a small number of qualifying players per season
(typically 3–5 mid-season EPL transfers with ≥450 total EPL minutes).
For ratings used in match prediction, "current club form" is arguably
*more* predictive than season aggregate, so this may have a mild
positive effect on prediction quality. The honest concern is the
*missing* portion (e.g., Rashford's Man Utd contribution) is silently
absent from total xG/xA accounting.

**Schema implication:** Our `player_season_stats` table has
`PRIMARY KEY (player_id, season, team)`, which would correctly support
split rows if the data source ever provided them. No schema change
needed if a future fix lands.

**Plan:** Re-evaluate in V1.02 — investigate whether Understat's
match-level endpoint (`read_player_match_stats`) provides per-team
totals we can aggregate ourselves.

### Per-90 metrics amplify small-sample noise
**What:** Players with low minutes (just above the 450-minute floor)
can post inflated per-90 numbers from a hot streak. Richarlison
appears at #2 with 471 minutes; Jhon Durán at #5 with 563 minutes.

**Mitigation:** 450-minute floor excludes the worst offenders but
doesn't eliminate the effect.

**Plan:** Add Bayesian shrinkage in V1.02 — pull low-minute ratings
toward the league mean, weighted by minutes played.

---

## V1.02

### Bayesian shrinkage uses a heuristic k, not empirical Bayes
**What:** We shrink per-90 ratings toward the league mean using
`shrunk = w × observed + (1-w) × prior`, with `w = minutes / (minutes + k)`
and `k = 900`. The choice of `k = 900` is a heuristic, not derived
from the data. It represents the "effective minutes of the prior" —
the minutes count at which a player is 50% observed, 50% prior. 900
minutes = 10 full matches.

**Evidence:** With `k = 900`, Joshua Zirkzee (560 min, raw 0.814)
shrinks to 0.459 and falls out of the 2025-2026 Top 10 — directly
addressing the small-sample problem flagged in the V1.01 plan above.
Established starters barely move: Haaland 0.944 → 0.781, Bruno
Fernandes 0.732 → 0.618.

**Impact:** The empirical Bayes alternative (`k = σ²_within / σ²_between`,
learned from the data) requires per-match player data to estimate
within-player variance. We have only season aggregates from Understat.
The heuristic gets us most of the benefit (the rank fix) without
needing the data infrastructure.

**Plan:** Replace with empirical Bayes in V1.03, gated on per-match
data reconnaissance succeeding (see V1.03 task "Per-match data recon
+ integration"). If MD38 results suggest `k = 900` is too lenient
(small-sample players still over-ranked), bump to `k = 1350` as a
quick re-tune.

### Prior is league mean, not position-class mean
**What:** All players shrink toward the same prior (0.2390 — the
minutes-weighted league mean of ≥450-min rows). A forward and a
defender with the same minutes shrink toward the same value, even
though their natural rating distributions differ.

**Evidence:** Diagnostic priors computed during shrinkage:
- (i) all players, unweighted: 0.2428
- (ii) ≥450-min only, unweighted: 0.2428 (identical to (i) because
  the loader pre-filters at 450 min)
- (iii) ≥450-min, minutes-weighted: 0.2390 (used)

The spread across the three is 0.0037 — choice of prior method
barely matters at our current data scale.

**Impact:** Defenders are systematically pulled "up" toward the
league average (which is dominated by forwards/midfielders with
higher rating_per_90), and forwards are systematically pulled "down."
Small effect at low shrinkage (high-minute players) but more
meaningful at the filter floor.

**Plan:** Move to position-class-mean prior (separate prior per
GK/DEF/MID/FWD) in V1.03, gated on per-match data providing
player-level position info. Season-aggregated stats from Understat
don't carry position.

### Form-vs-consistency weighting is a judgment call
**What:** We store two shrunk values per row — `shrunk_form` (per-row
shrinkage, captures recent form) and `shrunk_consistency` (career
minutes-weighted aggregate, captures stable ability). The simulator
blends them as `0.75 × form + 0.25 × consistency` via a `form_weight`
parameter logged per prediction.

**Evidence:** The 0.75 ratio is not derived from data. It reflects
the judgment that established players retain value during form dips
(injuries, transfers, big-match factor). Inspection of the largest
form-vs-consistency gaps in 2025-2026 confirms the model would benefit
from a non-zero consistency weight: Alexander Isak (Newcastle →
Liverpool, 717 min) has form 0.361 vs consistency 0.633, a gap of
-0.273. Cole Palmer at Chelsea is in a genuine form slump (1917 min,
form 0.316, consistency 0.518).

**Impact:** Predictions for transfer-window players, injury-return
players, and players in slumps will tilt slightly toward their career
baseline rather than purely chasing current-season noise.

**Plan:** Empirically tune `form_weight` after MD38 results. If
predictions feel "form-blind" (over-weighting career when current
form is signal), drop toward 0.5. If they feel chasing-noise, push
toward 0.85. Logged per-prediction so retrospective tuning is easy.