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