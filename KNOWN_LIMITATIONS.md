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

### Realistic XI selection uses heuristic position multipliers + hybrid slot bonuses
**What:** XI selection for each team-season runs the Hungarian assignment
algorithm (`scipy.optimize.linear_sum_assignment`) over a cost matrix
built from blended shrunk ratings (0.75 × form + 0.25 × consistency)
multiplied by position-class weights and slot bonuses:
- Class multipliers: DEF = 2.0, MID = 1.25, FWD = 1.0, GK = locked-in
  by minutes
- Hybrid slot bonus: 1.1× for players whose Understat eligibility
  includes both halves of a hybrid role (DEF+MID for DM/LWB/RWB slots,
  FWD+MID for CAM slots)

**Evidence:** First attempt used DEF=4, MID=2, FWD=1 and produced
catastrophically defender-heavy XIs (135 DEF vs 16 FWD across 20 teams,
~7 defenders per team). After dropping to DEF=2/MID=1.5/FWD=1 with
hybrid bonus 1.2, MID-heavy formations dominated (14/20 teams' best
fit was 4-2-3-1). Further tuning to MID=1.25 / bonus=1.1 made minor
differences (1 team flipped to 4-4-2 as #1, total class distribution
barely moved). The model's behavior is now dominated by formation
shape, not multipliers — exactly the design intent.

**Impact:** Realistic XIs that match roster-strength intuition. Liverpool's
top fit is 3-4-2-1 with Salah at MID — defensible given his drift between
roles, but acknowledges the model exploits hybrid eligibility for MID
slots (1.25 × 1.1 = 1.375x effective weight) over pure FWD slots (1.0x).
A pure forward without midfielder eligibility will rank lower at FWD
than a hybrid will at MID for equal raw rating.

**Plan:** Re-tune when MD38 predictions land. If results suggest the
formation distribution doesn't match real outcomes, drop MID toward
1.0 or remove the hybrid stack entirely (use max-of, not multiply).

### Wing-backs are classified as DEF, not MID
**What:** In all back-3/back-5 formations (3-4-3, 3-5-2, 3-4-2-1,
5-3-2, 5-4-1), the LWB and RWB slots are seeded with `position_class`
= DEF, not MID.

**Evidence:** Wing-backs structurally are part of the defensive line
but functionally provide width and attacking output. Classifying them
correctly is a play-style question that V1.03's per-match data will
resolve.

**Impact:** A pure wing-back (Frimpong, Bogle, Hume) gets weighted as
a DEF (2.0x multiplier), which over-weights their attacking
contribution. In practice, hybrid eligibility usually triggers the
slot bonus, so the effective multiplier is 2.0 × 1.1 = 2.2x for
wing-back-positioned hybrid players.

**Plan:** V1.03 per-match data + SoFIFA play-styles will allow
position assignment by actual role rather than formation slot.

### Multi-position handling: first-token-wins for primary class, full set for eligibility
**What:** Understat returns a `position` field as a space-separated
string of single-letter codes (e.g. 'D M S' for a defender who also
played midfield, where 'S' marks substitute appearances). Two parallel
stores derived from this:
- `player_season_stats.position_class` = the first non-S token's class,
  representing the "primary role" Understat thinks the player plays.
- `player_positions` (separate table) = one row per (player, season,
  team, position_class) with a `priority` field (1 = primary, 2+ =
  secondary). Used for multi-eligibility in lineup selection.

A consistency invariant is enforced at backfill time: every
`player_season_stats` row must have a `priority=1` row in
`player_positions` with matching class.

**Evidence:** ~30% of EPL players in 2025-2026 have multi-class
eligibility (e.g., Szoboszlai → DEF, FWD, MID; Salah → FWD, MID).

**Impact:** Lineup selection considers all eligible classes per
player. The first-token-wins primary class is used wherever a single
class is needed (shrinkage prior calc by class — deferred to V1.03 —
and convenience queries).

**Plan:** V1.03 per-match data will allow per-position minutes-weighted
priority instead of trusting Understat's ordering. Inverted wingers in
3-4-2-1 (currently classified RW/LW/CAM) will get proper
inside-forward designation.

### `best_xi` is a standalone artifact, not tied to fixtures
**What:** The `best_xi` table holds top-3 ranked XIs per team-season
across all 10 formations, independent of any fixture. Schema is
keyed on `(season, team, formation, rank, slot_no)`.

**Evidence:** S8 found MD38 fixtures were never loaded into the
`fixtures` table (only the trial fixture exists). Rather than block
on fixture loading, lineup selection was shipped as a standalone
queryable artifact.

**Impact:** Predictions cannot run end-to-end against `best_xi`
directly — they need a fixture to anchor scenarios. The next step
(MD38 prediction run) requires loading MD38 fixtures into `fixtures`
and bridging via `lineup_scenarios + scenario_teams + fixture_lineups`,
using `best_xi` rows as the lineup source.

**Plan:** Load MD38 fixtures + season string normalization (the
`fixtures` table currently uses '2024-25' short form, while
`player_season_stats` uses '2024-2025' — needs reconciliation).
Then write a fixture-to-scenario bridge.

### Formation library is 10 four-defender and three-defender shapes
**What:** Library: 4-3-3, 4-2-3-1, 4-4-2, 4-1-4-1, 4-5-1, 3-4-3,
3-5-2, 3-4-2-1, 5-3-2, 5-4-1. Excludes 3-3-3-1 (rare), 4-3-1-2 (narrow
diamond, rare in EPL), and 4-2-2-2 (more common in Germany/Brazil).

**Evidence:** Initial library was 4 formations (all back-4). S8
expanded to 10 to enable real "which formation fits this roster best"
analysis. Selection results: 13/20 teams' #1 is 4-2-3-1, 6/20 is
3-4-2-1, 1/20 is 4-4-2. Matches modern EPL formation distribution
roughly.

**Impact:** A team that genuinely best fits a non-library formation
(e.g., narrow 4-3-1-2) gets matched to the closest library shape,
not its actual optimal.

**Plan:** Expand library as needed in V1.03+ if real-world fixture
results suggest specific formations are systematically missing.

### Total XI score uses outfielder scores only (GK contribution = 0)
**What:** `best_xi.total_xi_score` is the sum of the 10 outfielders'
`selection_score` values. The GK contributes nothing because:
1. GK is locked-in deterministically by most minutes — same player
   chosen regardless of formation.
2. GK's `rating_per_90` is near-zero (it measures npxG+xA, which GKs
   don't generate).

**Evidence:** No good signal exists in our data to score GK quality.

**Impact:** Two teams with identical outfielders but different GK
choices would tie on `total_xi_score`. In practice, every team has
one clear most-minutes GK, so this is a theoretical concern only.

**Plan:** V1.03+ with defensive metrics could add `xGA per 90 against`
or `clean sheets per 90` to the model and give GKs a real score
contribution.

### V1.02 ships with two simulator variants: unweighted (primary) and weighted (diagnostic)
**What:** The V1.02 simulator computes team strength two ways and writes
both predictions to the `predictions` table per fixture:
- `v1.02_unweighted`: strength = SUM(0.75 × shrunk_form + 0.25 ×
  shrunk_consistency) across the XI. Primary V1.02 model.
- `v1.02_weighted`: same blended rating × OFFENSIVE_WEIGHT[position_code]
  using an 18-code class-anchored weight table. Diagnostic only.

**Evidence:** On the MD38 fixture slate, the two variants disagreed by >5
percentage points on at least one outcome in 8 of 10 fixtures. The weighted
variant systematically pulls predictions toward equality (Sunderland-Chelsea:
unweighted 86% Chelsea win → weighted 48% Chelsea win; Crystal Palace-Arsenal:
unweighted 68% Arsenal win → weighted 36% Arsenal win). This contradicts
real-world league standings (Sunderland 19th, Chelsea top-6).

**Impact:** The weighted variant double-counts the position effect:
rating_per_90 is already an offensive metric (it's npxG+xA per 90), so
applying offensive position weights on top compresses the strength delta
between strong and weak teams. The unweighted variant produces more
calibrated predictions for top-vs-bottom matchups.

**Plan:** Keep both in predictions for retrospective comparison once MD38
results land (May 24, 2026). V1.03 should redesign position weighting
differently — possibly by applying weights to selection only (already done in
S8), OR by using position-conditional strength (e.g., counts of high-rated
forwards alone) instead of multiplying every player's rating.

### Linear-differential xG formula breaks at extreme strength gaps
**What:** `xG_away = max(0, BASE_GOALS - HOME_BONUS + K × (strength_away -
strength_home))`. When the home team's strength substantially exceeds the
away team's, away xG floors at zero.

**Evidence:** Manchester City vs Aston Villa unweighted: away xG = 0.22
(implying Villa nearly incapable of scoring). Villa are 4th in the EPL —
not a sub-0.5-xG side against anyone. The City strength advantage
(probably ~2.0+ blended rating units) overwhelms BASE_GOALS in the linear
formula.

**Impact:** Predictions for top-vs-bottom fixtures under-estimate underdog
scoring chances. The Poisson sim then under-predicts >1 goal away outcomes.

**Plan:** V1.03+ should consider:
1. A saturating xG function (e.g. `BASE_GOALS × exp(K × diff)` or logistic).
2. Strength normalization (e.g. divide each side's strength by league mean).
3. Empirical recalibration of `K` after seeing predicted-vs-actuals.

This is inherited from V1.01's calibration. V1.02 retains it for
comparability.