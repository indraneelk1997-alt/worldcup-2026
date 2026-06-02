# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S17 (first Cowork session, 2026-06-02)
**Current version line:** V1.04 ingest (multi-league)

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S17 start, HEAD was `24333f6 Add Cowork context files`;
  the entire `src/load/v2_ingest/` directory was untracked (S16 work
  never committed).
- Tags seen historically: `v1.02`, `md38-b12-prereg`, `md38-b2-prereg`.
- **Verify before trusting this** — run `git log --oneline -5` and
  `git status --short` first. (Observe, don't infer.)

## ✅ S17 outcome — V1.04 schema migration applied to live DB

Migration script: `src/load/v2_ingest/migrate_add_league_column.py`.
Two design issues from S16 were resolved with explicit verification:

1. **Split-commit fix (S16 lesson revisited).** Verified in-memory
   that DuckDB 1.5.2 still rejects ADD + UPDATE + SET NOT NULL in one
   transaction. Rewrote the migration to autocommit per statement, no
   outer transaction wrapping the loop. Trade-off: per-table failure
   semantics rather than all-or-nothing; idempotent re-run handles
   partial state. Verification helper was `_verify_split_commit.py`
   (now deleted).
2. **FK-dependency block (NEW S17 lesson).** The first live run failed
   on `games` — DuckDB refuses `ALTER COLUMN ... SET NOT NULL` on any
   table that other tables hold a declared FK into
   (duckdb/duckdb#17348). No DROP/ADD CONSTRAINT, no PRAGMA workaround
   exist. Adopted **mixed-enforcement policy**: tables without FK
   dependents get DB-level NOT NULL; tables with FK dependents get the
   column + backfill only, and app code must enforce non-nullity.
   Detection is dynamic at runtime via `duckdb_constraints()`. Folded
   into `Claude.md` "Recurring DuckDB gotchas".

Final state per target table after S17:

| Table                       | rows   | `league`   | NOT NULL? | Enforcement |
|-----------------------------|-------:|------------|-----------|-------------|
| games                       |    760 | backfilled | NO        | app code    |
| team_match_stats            |  1,520 | backfilled | YES       | DB          |
| player_match_stats          | 23,057 | backfilled | YES       | DB          |
| team_season_strength_v103   |     40 | backfilled | YES       | DB          |
| league_averages_v103        |      3 | backfilled | YES       | DB          |
| fixtures                    |     11 | backfilled | NO        | app code    |
| player_season_stats         |    793 | backfilled | YES       | DB          |

All rows backfilled with `'ENG-Premier League'`. NOT touched:
`players`, `formations`, `positions`, `formation_slots`, `best_xi`,
prediction tables (see `docs/v104_ingest_design.md`).

## Active task: V1.04 ingest module (build-sequence step 2)

`src/load/v2_ingest/ingest_understat.py` — parametrized by
`(league, season)`, append-only, `INSERT OR IGNORE`. Single file with
three table sections (games, player_match_stats, team_match_stats).
One Understat fetch per `(league, season)` pair.

**Hard precondition from S17 — app-code enforcement on `games` and
`fixtures`.** Every INSERT into these two tables MUST pass an explicit
`league` value, because their `league` column is nullable at the DB
level. For the 5 NOT-NULL tables this is DB-enforced; for `games` and
`fixtures` the loader must assert it itself. Bake this into the
loader's column-mapping section as a precondition, not a "remember to".

→ **Design conversation first** (per `Claude.md` rule 2) before code.
   Open questions worth resolving up front:
   - Where does `league` come from? Understat returns it natively
     (e.g. `'ESP-La Liga'`). Does the loader pass it through, or use
     the script's `(league, season)` parameter as the source of truth
     if they ever disagree?
   - Confirm the league-string format matches between what Understat
     returns and our `'ENG-Premier League'` PL labelling, before
     loading La Liga.

## After ingest works (build-sequence steps 3–5)

3. Test ingest on La Liga `2024-2025` + `2025-2026`.
4. If success, batch Serie A + Bundesliga + Ligue 1.
5. Regenerate `docs/db_schema.md`.

## Deferred

- Commit S17 work. End of session: `src/load/v2_ingest/` still
  untracked; Claude.md, docs/session_state.md, docs/db_schema.md all
  modified. Indraneel runs git.
- `derived_state_freshness` table + `check_freshness.py` tool.
- `docs/ingest_architecture.md`.
- soccerdata column-reference doc + pre-flight checklist (carry-forward
  from S15).

## Design decisions banked (don't relitigate)

From `docs/v104_ingest_design.md`:
1. INSERT OR IGNORE everywhere, no content-hash detection.
2. Append-only, no historical re-fetch.
3. One file per source, sectioned by table.
4. Explicit `derived_state_freshness` tracking, manual refresh control.
5. Incremental migration via `src/load/v2_ingest/`.

Plus:
- **Option B for the league column** (NOT NULL, no DEFAULT) — modulated
  by the S17 **mixed-enforcement policy**: DB-level NOT NULL on 5 of 7
  target tables, app-code enforcement on `games` + `fixtures` (the two
  tables other tables hold declared FKs into).
- Migration is intentionally re-runnable; per-table failure semantics.
- No outer transaction wraps a multi-step DuckDB migration. Per-statement
  autocommit, idempotency in the script.
