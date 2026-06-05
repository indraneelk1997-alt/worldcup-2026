# V1.04 Understat ingest — design

**Status**: design captured, implementation pending.
**Designed in**: S18 (2026-06-02).
**Implements**: build-sequence step 2 from `docs/v104_ingest_design.md`
(first V2 loader; pattern for future source-centric ingest files).
**Supersedes**: nothing yet. V1.03 loaders (`backfill_player_match.py`,
`team_match_load.py`, `load_md38_actuals.py`) remain in place per the
incremental migration rule.

## Scope

A single parametrized loader that ingests one `(league, season)` pair
of Understat data, populating three tables in one fetch:

- `games`              — schedule rows
- `player_match_stats` — per-player per-match rows
- `team_match_stats`   — per-team per-match rows (unpivoted from
                         Understat's per-match home/away pairs)

**Not in scope** (deliberately):

- `fixtures`           — upcoming matches; separate concern, separate
                         loader. The S17 mixed-policy obligation
                         (app-code enforcement of `league NOT NULL`)
                         carries over to whatever loader touches it.
- `player_season_stats`— heavily derived (`shrunk_form`, `position_class_v103`,
                         …); not raw Understat. Stays in its own
                         derive step, independent of ingest.
- `derived_state_freshness` updates — deferred per `v104_ingest_design.md`.

## Ground truth confirmed in S18 (probes, both deleted after)

Probe 1 (`_probe_understat_league.py`):

- Understat returns `'ENG-Premier League'` and `'ESP-La Liga'` as the
  `league` MultiIndex value. Exact match with the S17 PL backfill string.
  No translation needed for league.
- `season` MultiIndex value is `'2425'` / `'2526'`. Our DB stores
  `'2024-2025'` / `'2025-2026'`. Translation needed (same `SEASON_MAP`
  as V1.03 uses; reproduce, don't import — V1.03 is deprecated).
- All three Understat endpoints (`read_schedule`,
  `read_player_match_stats`, `read_team_match_stats`) return a
  MultiIndex with `league` at level 0. One assertion at the top covers
  all three sections.

Probe 2 (`_probe_team_match_stats.py`):

- `read_team_match_stats` returns **one row per game** (380 rows/season)
  with paired `home_*` / `away_*` columns
  (`home_goals`/`away_goals`, `home_xg`/`away_xg`, etc.).
- Our DB's `team_match_stats` is **two rows per game** (one per team)
  with `goals`/`opponent_goals` mirroring. The loader unpivots:
  one Understat row → two DB rows. Existing DB row count (1,520 = 2 ×
  760) confirms this is the V1.03 shape too.

## Design decisions

### 1. League: passthrough with assertion (Option C)

The loader uses Understat's `league` value in INSERT statements, but
asserts it matches the script's `--league` parameter before
proceeding. Disagreement → hard fail with both values printed.

Rationale: passthrough alone trusts Understat blindly; parameter-only
silently masks operator error. Asserting catches both classes of
failure (operator error, Understat contamination).

### 2. `effective_position` derivation: extracted, V1.04-owned

The V1.03 logic in `backfill_player_match.py` is extracted into
`src/load/v2_ingest/_position_policy.py` and imported by
`ingest_understat.py`. V1.03 files are NOT updated to import from it
— the V1.04 architecture doc's rule is "V1 loaders only migrate when
they break." Two duplicate copies in V1.03 remain (drift risk already
flagged in their docstrings); V1.04 is the third copy moved to a clean
home.

Future: if `backfill_player_match.py` or `load_md38_actuals.py` ever
breaks, fix-forward by switching it to import from `_position_policy.py`.

### 3. New-league fallback: accept `'Sub'` (load-order decision (a))

V1.03's policy-C fallback chain for sub-only players:
1. Player's most-common non-Sub position **in this dataset**.
2. Map from `player_season_stats.position_class` for that player.
3. Else: `effective_position = 'Sub'`.

For a fresh non-PL ingest, `player_season_stats` has zero rows for
that league's players, so step 2 is effectively a no-op and rare
sub-only players land on step 3. `'Sub'` is a valid `effective_position`
value in the existing schema (`player_match_schema.py` line 97
defines it NOT NULL but doesn't constrain values).

Alternative considered: derive `player_season_stats` for the new
league first, so step 2 can fire. Rejected — it expands ingest scope
into derived state, which the V1.04 architecture explicitly keeps
separate and manually refreshed.

### 4. Team-match shape: unpivot in app code

Understat's per-game shape is unpivoted in Python before the INSERT,
not via SQL. Two reasons: the shape difference is loader-private (no
downstream code should see the per-game shape), and Python `melt`-style
code is easier to read than a SQL `UNION ALL` of explicit column
selects.

For each Understat row, the loader yields:
- `(team=home_team, side='home', opponent=away_team, goals=home_goals,
   opponent_goals=away_goals, xg=home_xg, opponent_xg=away_xg, …)`
- `(team=away_team, side='away', opponent=home_team, goals=away_goals,
   opponent_goals=home_goals, xg=away_xg, opponent_xg=home_xg, …)`

### 5. No outer transaction; per-section autocommit (S17 carry-forward)

The loader does NOT wrap the three sections in one `BEGIN/COMMIT`.
Each `INSERT OR IGNORE` autocommits. If section B fails, section A's
rows are already persisted, and `INSERT OR IGNORE` makes a re-run
idempotent. Matches the S17 migration's failure semantics.

(Note: this is a relaxed posture compared to "all three sections
ought to be one logical atomic ingest." We accept the relaxation
because INSERT OR IGNORE makes re-running cheap and observable, and
DuckDB's transaction semantics around multi-statement DDL/DML migration
mode were the original S16 + S17 problem we're not relitigating.)

### 6. Idempotency: INSERT OR IGNORE (banked from v104_ingest_design.md)

No content-hash detection. Re-running the loader for an already-loaded
`(league, season)` is a no-op: every row hits its PK and gets skipped.
The loader reports `(inserted, skipped_as_duplicate)` per section so
the operator can see whether work happened.

### 7. App-code enforcement of `league NOT NULL` on `games`

Per S17 mixed-enforcement policy, `games.league` is nullable at the DB
level (FK dependents block `SET NOT NULL`). The loader's `games`
section therefore asserts `league IS NOT NULL` on every constructed row
before the INSERT, raising loudly if anything slipped through. This is
the only S17 obligation that applies to this loader (it doesn't touch
`fixtures`).

### 8. Implicit `players` dimension maintenance inside Section B

`player_match_stats.player_id` declares a FK to `players.player_id`
(per `docs/db_schema.md`). For any fresh-league load, the dataset's
player_ids are not yet in `players` and the INSERT would fail wholesale
on FK violation. (Missed in the initial S18 design pass; caught at the
S18 dry-run review because `read_only=True` masked it.)

Mirroring V1.03 (`backfill_player_match.py` step 10a;
`load_md38_actuals.py` analogous block), the loader extracts distinct
`(player_id, player_name)` pairs from the Understat data (the
`player_id` column + the `player` MultiIndex level) and
`INSERT OR IGNORE`s them into `players` BEFORE the
`player_match_stats` INSERT.

This is implemented inside Section B rather than as a separate section
because: (a) the data source is the same `read_player_match_stats`
frame, not a distinct Understat endpoint; (b) `players` is a dimension
table maintained as a side effect of any source that mentions players,
not an "ingest target" in the source-centric sense; (c) keeping it
in Section B keeps the design's "three Understat endpoints, three
sections" mental model intact.

The loader sanity-checks that each `player_id` maps to exactly one
`player_name` within the dataset, and fails loudly if not (would
indicate either Understat data quality issue or our extraction bug).

## Loader interface

```
uv run python src/load/v2_ingest/ingest_understat.py \
    --league "ESP-La Liga" \
    --season "2024-2025"
```

- `--league`: full Understat string. Validated against soccerdata's
  known leagues (currently top-5 European).
- `--season`: DB-format string (`'2024-2025'`). Translated internally
  to Understat's `'2425'`.
- `--dry-run` (optional): fetches and transforms; prints what would be
  inserted; makes no DB writes.

## Test plan

1. **La Liga 2024-2025**, dry-run. Eyeball: row counts (expect 380
   games, ~10–12k player-match rows, 760 team-match rows), league
   passthrough assertion holds, no NULL leagues, effective_position
   distribution looks reasonable.
2. La Liga 2024-2025, live. Re-query DB to confirm rows landed.
3. La Liga 2025-2026, live.
4. Re-run La Liga 2024-2025 — should be 100% skipped-as-duplicate
   (idempotency check).
5. Only after La Liga is clean: Serie A, Bundesliga, Ligue 1 in batch.

## References

- `docs/v104_ingest_design.md` — overall V2 ingest architecture.
- `docs/session_state.md` (S17) — mixed-enforcement policy origin and
  table-by-table status.
- `Claude.md` — DuckDB gotchas, soccerdata notes.
- V1.03 derivation source: `src/load/backfill_player_match.py`
  (`compute_effective_position`, lines 78–139).
