# Player Coverage Index (design)

> **Status:** PROPOSED (S44) — schema for sign-off before the loader is built.
> Reusable per-player data-coverage index. Feeds the dashboard "Squad coverage"
> page now; intended as the shared substrate for future player-profile / ratings
> visuals. Companion to `docs/item9_xi_selection.md` (the eligibility layer it
> summarises).

## Why this exists

Two needs converged:

1. **Surface coverage** — eyeball, per nation, which of the 23 squad players we
   actually have data for, by source, with a team-level rating. (S43 showed the
   cost of *not* seeing this: `ea_id = NULL` players like Danilo Luiz / Ken Sema
   are selectable but unrateable → they blanked the dashboard.)
2. **Index for reuse** — a single, queryable per-player record of "what do we
   know about this player and how good is our coverage," so later features
   (player profile cards, ratings breakdowns, swap UIs) read from one place
   instead of re-deriving source joins each time.

So this is a **derived rollup table**, one row per squad player, in the same
spirit as `squad_position_eligibility` (item 9): built read-only against the full
DB by a loader, `CREATE OR REPLACE`, **no FK, never writes a source table**
(Claude.md rule 9). It then flows into the trimmed dashboard DB automatically via
`make_dashboard_db.py` (exclusion-based copy — it auto-included
`squad_position_eligibility` in S42, same mechanism), so the live page just
*reads* it. This is the key design move: **StatsBomb minutes are computed once at
build time against the full DB** (the trimmed DB drops `statsbomb_event`), then
frozen into the index — the dashboard never needs the raw event table.

## Sources (the columns we can populate)

| Source | Where | Per-player signal |
|---|---|---|
| Understat | `player_match_all` (view, `source='understat'`) | club minutes |
| FBref | `player_match_all` (view, `source='fbref'`) | club minutes |
| StatsBomb | `statsbomb_player_match` (minutes) + `statsbomb_event` (position) | intl minutes |
| EA FC26 | `ea_fc26_player` (joined via `wc2026_squad.ea_id`) | has base attrs + position |
| Adjusted attrs | `player_adjusted_attributes_wide` (732 rows) | **model-ready** (rateable) |
| Eligibility basis | `squad_position_eligibility.basis` | empirical / ea_fallback / group_fallback |

## Proposed table: `player_coverage_index` (1 row per squad_row_id, ~1247)

**Identity** (from `wc2026_squad`, so profile visuals don't re-join):
`squad_row_id` (key), `nation_code`, `nation_name`, `player_name`, `name_norm`,
`primary_position_group` (GK/DEF/MID/FWD), `position_class`, `ea_id` (nullable),
`our_player_id` (nullable), `caps`, `shirt_no`, `club`, `dob`.

**Per-source coverage:**
`understat_minutes`, `fbref_minutes`, `statsbomb_minutes` (INTEGER, 0 if none),
`empirical_minutes_total` (sum of the three), `n_empirical_sources` (0–3),
`has_ea` (BOOL — `ea_id` present in `ea_fc26_player`),
`has_adjusted` (BOOL — present in `player_adjusted_attributes_wide` → **the
model-ready / rateable flag**).

**Tier & score** (the reusable rating primitives):
- `coverage_basis` (VARCHAR) — passthrough of the eligibility layer's own view.
- `coverage_tier` (VARCHAR) — one display label per player, ordered by how good
  our coverage is. `has_adjusted` is the dividing line (rateable vs not):

  | tier | rule | score | badge |
  |---|---|---|---|
  | `empirical+rated` | `has_adjusted` AND `empirical_minutes_total ≥ 270` | 1.0 | green |
  | `rated` | `has_adjusted`, < 270 empirical min (leans on EA-adjusted) | 0.8 | light green |
  | `empirical_unrated` | NOT rateable but ≥ 270 empirical min (real data, `ea_id` NULL → no adjusted attrs; the fix-the-EA-crosswalk bucket — e.g. Danilo Luiz, Ken Sema) | 0.5 | orange |
  | `ea_only` | not rateable, `basis = ea_fallback` | 0.4 | amber |
  | `group_only` | `basis = group_fallback` (coarsest) | 0.2 | red |
  | `none` | nothing | 0.0 | grey |
  | `gk` | goalkeeper (rated separately, no adjusted-attrs row) | — (excluded) | neutral |

- `coverage_score` (DOUBLE, 0–1, NULL for GK) — drives the weighted team rating.
  **Tunable**; weights as in the table above.

  The `empirical_unrated` tier was added during build (S44): the original 5-tier
  ladder assumed "not rateable ⟹ EA/group fallback", but a player with real
  empirical minutes and `ea_id IS NULL` is neither — it's an actionable linkage
  gap, so it gets its own tier rather than being mislabelled `none`.

## Team rating (the page header — "show both")

Computed by aggregating the index per nation (no separate table needed; a thin
`team_coverage` view is optional later):
- **% model-ready** = `mean(has_adjusted)` over the squad — the headline that
  flags the dark-screen class directly.
- **Weighted tier score** = `mean(coverage_score) × 100` — rewards *depth* of
  real data, not just rateable-or-not.

## Decisions (signed off S44)

1. **Tier cut-points** — DECIDED: keep the 270-min empirical floor (matches item
   9's eligibility floor) for `empirical+rated` vs `rated`; `coverage_score`
   weights `1.0 / 0.8 / 0.5 / 0.2 / 0.0`.
2. **Match counts** — DECIDED: add `*_matches` per source alongside minutes
   (`understat_matches`, `fbref_matches`, `statsbomb_matches`). Source match-id
   column to be confirmed live before the loader counts them.
3. **GKs** — DECIDED: `coverage_tier = 'gk'` (neutral), excluded from the team
   `coverage_score` aggregate. They have no adjusted-attrs row by design.
