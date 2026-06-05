# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S19 (2026-06-05)
**Current version line:** V1.04 ingest (multi-league)

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S19 start, HEAD was `7504687 S18: V1.04 Understat
  ingest; La Liga 2024-25 + 2025-26 loaded`. `docs/db_schema.md` was
  modified-uncommitted (carryover from end of S18).
- S19 work uncommitted at end of session (see Deferred).
- **Verify before trusting this** — run `git log --oneline -5` and
  `git status --short` first. (Observe, don't infer.)

## ✅ S19 outcome — Big 3 loaded; 9 of 10 (league, season) pairs in

### What shipped
- `src/tools/validate_v104_ingest.py` — new post-load validation
  script. Read-only. Reports coverage matrix per `(league, season)`,
  NULL-league audit, game/team/player counts, the 2× team_match
  invariant, FK integrity spot-checks, grand totals, cross-league
  carryover. Used as the close-out diagnostic for S19; should be
  re-run any time we add or repair a league.
- Six load attempts via a bash double-loop over
  `{Serie A, Bundesliga, Ligue 1} × {2024-2025, 2025-2026}`.

### Load results

| League / Season              | games | player_match | team_match | players added |
|------------------------------|------:|-------------:|-----------:|--------------:|
| ITA-Serie A     2024-2025    |   380 |       11,888 |        760 |     (no log, in chain after carryover) |
| ITA-Serie A     2025-2026    |   380 |       11,928 |        760 |     (some partial-resume from interrupted batch) |
| GER-Bundesliga  2024-2025    |   **0** | **0**      |    **0**   |     **FAILED — see below** |
| GER-Bundesliga  2025-2026    |   306 |        9,555 |        612 |    459 |
| FRA-Ligue 1     2024-2025    |   306 |        9,413 |        612 |    455 |
| FRA-Ligue 1     2025-2026    |   306 |        9,386 |        610 |    240 |

DB grand totals after S19:
- `games`             : 3,198 rows
- `players`           : 3,465 rows
- `player_match_stats`: 99,079 rows
- `team_match_stats`  : 6,394 rows
- 7 league-bearing tables: zero NULL `league` values
- FK integrity: zero orphans across all checked relationships
- 266 player_ids appear in 2+ leagues (cross-league
  transfers / shared IDs)

### ⚠️ OPEN — GER-Bundesliga 2024-25 NOT loaded

Source of failure (verified, not inferred): soccerdata's own parser,
not our loader.

```
File ".../soccerdata/understat.py", line 688, in _read_match
    home_team_id = next(iter(rosters["h"].values()))["team_id"]
AttributeError: 'list' object has no attribute 'values'
```

`rosters["h"]` was expected to be a dict-like; Understat returned a
list for at least one match in this season. Our loader fetches all
three Understat endpoints before any DB write, so this one parser
crash aborted the entire `(GER-Bundesliga, 2024-2025)` ingest before
section A. **Zero rows present for this pair — nothing to clean up.**

Web search at S19 close turned up no specific patched issue for this
exact AttributeError; soccerdata's general pattern is fragility to
Understat HTML/JSON changes (see refs).

### Notes worth banking

- **FRA-Ligue 1 2025-26 has 306 games but only 305 team_match rows.**
  Understat's `read_team_match_stats` returned 305 for this season;
  probably one postponed or in-progress fixture. Our code is fine
  — this is an Understat source gap. Captured by `validate_v104_ingest.py`
  section 5 (invariant check still passes because the join is on the
  305 games with team_match data; the 306th game appears in `games`
  but is unjoined).
- **Some duplicate-row counts were non-zero** in Section B for the
  Serie A 2025-26 carryover (`inserted=2163, skipped_as_duplicate=9765`).
  That's expected: the interrupted batch had partially loaded that
  pair; INSERT OR IGNORE on re-run skipped already-present rows and
  filled the rest. Idempotency working as designed.

## Active task at S20 start: resolve GER-Bundesliga 2024-25

Path forward (per S19 discussion, deferred deliberately):

1. **Check soccerdata version.** `uv pip show soccerdata`. If we're
   behind the latest release on PyPI / GitHub, try
   `uv add soccerdata --upgrade` — a maintainer may have pushed a
   fix for this specific parser failure. Cheapest move; ~5 min.
2. **If upgrade doesn't help: per-match workaround.** Iterate the
   season's match_ids ourselves, call
   `us.read_player_match_stats(match_id=X)` per game wrapped in
   try/except, build a partial DataFrame, log which matches failed.
   ~50 lines of throwaway code. We'd load all games except the bad
   one(s) and document the gap.
3. **Open a soccerdata issue** with a minimal repro. (Optional, but
   the maintainer is responsive per the repo's issue history.)
4. Re-run `validate_v104_ingest.py` after; should report 10/10
   `(league, season)` coverage.

## After GER fix (build-sequence step 5)

5. Regenerate `docs/db_schema.md` once GER is in. Total
   player_match_stats rows should land around ~109k after GER 24-25.
6. `derived_state_freshness` table + `check_freshness.py` tool
   (deferred from V1.04 design doc).

## Deferred

- **Commit S19 work** at session start. Modified at end of S19:
  - `docs/session_state.md` (this file)
  - `docs/db_schema.md` (carryover from S18; regenerate again after
    GER fix so it reflects the final coverage)
  - `src/tools/validate_v104_ingest.py` (new)
- GER-Bundesliga 2024-25 load (see Active task above).
- `derived_state_freshness` table + `check_freshness.py` tool.
- `docs/ingest_architecture.md`.
- soccerdata column-reference doc + pre-flight checklist
  (carry-forward from S15).
- Recompute `player_season_stats` for the newly-loaded leagues so
  policy-C step 2 starts firing for them. Per S18 decision (a) this
  is not blocking; current 'Sub' fallback is acceptable.

## Design decisions banked (don't relitigate)

From `docs/v104_ingest_design.md`:
1. INSERT OR IGNORE everywhere, no content-hash detection.
2. Append-only, no historical re-fetch.
3. One file per source, sectioned by table.
4. Explicit `derived_state_freshness` tracking, manual refresh control.
5. Incremental migration via `src/load/v2_ingest/`.

From S17 (`Claude.md`):
- Mixed-enforcement NOT NULL: DB-level on 5 of 7 league-bearing
  tables; app-code on `games` + `fixtures`.
- No outer transaction wraps multi-step DuckDB migrations.

From S18 (`docs/v104_ingest_understat.md`):
- Option C (passthrough + assertion) for league source-of-truth.
- effective_position extraction to `_position_policy.py`; V1.03
  stays untouched.
- New-league fallback (decision (a)): sub-only players in fresh
  leagues land on `'Sub'`.
- `players` dimension maintenance lives inside Section B, not a
  separate section.

From S19:
- Validation script as the standard post-load eyeball, not
  ad-hoc SQL. Re-run after any league add or repair.
- 9 / 10 coverage with one known gap is an acceptable shippable
  state; soccerdata fragility on specific matches is a real and
  recurring risk worth designing around (per-match try/except
  pattern documented above for the eventual workaround).

## References

- soccerdata GitHub: https://github.com/probberechts/soccerdata
- soccerdata issue tracker (filter "understat"):
  https://github.com/probberechts/soccerdata/issues
- Related but distinct failure mode (KeyError 'statData'):
  https://github.com/probberechts/soccerdata/issues/904
- soccerdata docs (Understat scraper):
  https://soccerdata.readthedocs.io/en/stable/reference/understat.html
