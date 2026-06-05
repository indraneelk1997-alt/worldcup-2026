# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S18 (2026-06-04)
**Current version line:** V1.04 ingest (multi-league)

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S18 start, HEAD was `c5bc110 S17: V1.04 league
  column migration (mixed enforcement) applied`.
- S18 work uncommitted at end of session (see Deferred).
- **Verify before trusting this** — run `git log --oneline -5` and
  `git status --short` first. (Observe, don't infer.)

## ✅ S18 outcome — V1.04 Understat ingest landed; La Liga loaded clean

### What shipped
- `docs/v104_ingest_understat.md` — design doc capturing all S18
  decisions (Option C league policy, load-order (a), effective_position
  extraction, unpivot, Section-B players precondition).
- `src/load/v2_ingest/_position_policy.py` — extracted
  `compute_effective_position` from V1.03 (byte-for-byte logic; V1.03
  files NOT updated per architecture doc's "migrate on break" rule).
- `src/load/v2_ingest/ingest_understat.py` — V1.04 loader, parametrized
  by `(league, season)`. Three sections (games, player_match_stats,
  team_match_stats), with implicit `players` dimension maintenance
  inside Section B. INSERT OR IGNORE everywhere; no outer transaction
  (S17 carry-forward).
- `Claude.md` — appended several soccerdata/Understat gotchas
  discovered during S18 (MultiIndex shape, season translation,
  whole-game duplicates, `players` FK ordering).

### La Liga ingest results

| Season  | games | player_match | team_match | players added |
|---------|------:|-------------:|-----------:|--------------:|
| 2024-25 |   380 |       11,900 |        760 |           574 |
| 2025-26 |   380 |       11,952 |        760 |           234 |

DB state after S18:
- `games`            : 1,520 rows (760 PL + 760 La Liga)
- `players`          : 1,564 rows
- `player_match_stats`: 46,909 rows
- `team_match_stats` : 3,040 rows

### Anomalies observed and resolved

1. **Initial dry-run masked a FK gap.** V1.03 populates `players`
   before `player_match_stats` because of the declared FK. I missed
   this on the first design pass; the dry-run didn't surface it
   because the read-only connection never attempts inserts. Caught on
   review of the first dry-run output. Loader + design doc patched
   before any live run.
2. **32 duplicate rows in La Liga 2025-26 player_match.** All from a
   single game (`game_id=29482`, Villarreal vs Real Oviedo); each
   duplicate group is byte-for-byte identical. Understat source-data
   quirk. INSERT OR IGNORE drops the redundant copy with no
   information loss. Gotcha banked in `Claude.md`.

### Test plan execution (from `docs/v104_ingest_understat.md`)
1. La Liga 2024-25, dry-run ✅
2. La Liga 2024-25, live ✅
3. La Liga 2025-26, dry-run ✅
4. La Liga 2025-26, live ✅
5. Re-run La Liga 2024-25 (idempotency) ✅ — all sections 100% skipped

## Active task: Big 3 leagues (build-sequence step 4)

Load Serie A, Bundesliga, Ligue 1 — each for both 2024-2025 and
2025-2026 seasons. Same loader, no code changes expected.

Pattern per league:
```
uv run python src/load/v2_ingest/ingest_understat.py \
    --league "<LEAGUE>" --season "2024-2025" --dry-run
# eyeball
uv run python src/load/v2_ingest/ingest_understat.py \
    --league "<LEAGUE>" --season "2024-2025"
# repeat for 2025-2026
```

League strings (verified in `SUPPORTED_LEAGUES`):
- `"ITA-Serie A"`
- `"GER-Bundesliga"`
- `"FRA-Ligue 1"`

Expected per-season-per-league shape:
- 306 games for Bundesliga (18 teams × 34 matchdays) — NOT 380.
  Serie A and Ligue 1 are 20×38 = 380 each.
- player_match: 10–13k rows each (proportional to game count).
- team_match: 2 × game count.
- New players: ~500–600 first season per new league; ~200–300 second.

Watch for:
- Per-game duplicate quirks like La Liga 29482 — show up as
  `skipped_as_duplicate > 0` in Section B. Benign unless the
  group has non-identical rows; the `_probe_dup_player_match.py`
  pattern is the diagnostic recipe if anything looks off.
- FK conflicts on `team_match_stats` if a referenced `game_id` somehow
  isn't in `games` (shouldn't happen — same fetch, same Understat
  scraper).

## After Big 3 (build-sequence step 5)

5. Regenerate `docs/db_schema.md` — total rows in player_match_stats
   should be ~80–100k after all 4 non-PL leagues × 2 seasons each.

## Deferred

- **Commit S18 work** at session start. Modified at end of S18:
  - `Claude.md` (gotchas)
  - `docs/session_state.md` (this file)
  - `docs/v104_ingest_understat.md` (new)
  - `src/load/v2_ingest/_position_policy.py` (new)
  - `src/load/v2_ingest/ingest_understat.py` (new)
  - Three throwaway probes also created mid-S18, to be deleted before
    commit: `_probe_understat_league.py`, `_probe_team_match_stats.py`,
    `_probe_dup_player_match.py`.
- `derived_state_freshness` table + `check_freshness.py` tool.
- `docs/ingest_architecture.md`.
- soccerdata column-reference doc + pre-flight checklist
  (carry-forward from S15).
- Recompute `player_season_stats` for the newly-loaded leagues, so
  policy-C step 2 starts firing for them. Not blocking; current
  fallback to `'Sub'` for sub-only players is acceptable per
  design doc decision (a).

## Design decisions banked (don't relitigate)

From `docs/v104_ingest_design.md`:
1. INSERT OR IGNORE everywhere, no content-hash detection.
2. Append-only, no historical re-fetch.
3. One file per source, sectioned by table.
4. Explicit `derived_state_freshness` tracking, manual refresh control.
5. Incremental migration via `src/load/v2_ingest/`.

From S17 (`docs/session_state.md` history, `Claude.md`):
- Mixed-enforcement NOT NULL: DB-level on 5 of 7 league-bearing
  tables; app-code on `games` + `fixtures`.
- No outer transaction wraps multi-step DuckDB migrations.

From S18 (`docs/v104_ingest_understat.md`):
- Option C (passthrough + assertion) for league source-of-truth.
- effective_position extraction to `_position_policy.py`; V1.03
  stays untouched.
- New-league fallback (decision (a)): sub-only players in fresh
  leagues land on `'Sub'`.
- `players` dimension maintenance lives inside Section B, not as a
  separate section.
