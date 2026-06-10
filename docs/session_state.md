# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S20 (2026-06-10)
**Current version line:** V1.04 ingest — Understat at 9/10; FBref
competitions/internationals in design phase

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S20 start, HEAD was
  `f6d0768 S19: Big 3 ingest (9/10 league-seasons); GER 2024-25 deferred`.
  S19 work *was* committed (the previous session_state.md was stale on
  that claim — corrected here).
- S20 close commit (intended): see "Commit message" below.
- **Out-of-repo state worth knowing:**
  `~/soccerdata/config/league_dict.json` overlay was written during S20
  Phase 2a, currently contains the `UEFA-Champions League` entry.
  Not in-repo yet → not reproducible on a fresh checkout. **S21 step 1.**
- Verify before trusting: `git log --oneline -5` and
  `git status --short`. (Observe, don't infer.)

## S20 outcome — Path A confirmed; ingest scope expanded; GER quick-check exhausted

### What we tried for GER-Bundesliga 2024-25 (the planned S20 task)

- `uv pip show soccerdata` → **1.9.0**.
- `uv add soccerdata --upgrade` resolved 161 pkgs, bumped 18 sub-deps
  (lxml, requests, selenium, certifi, idna, …) but **did NOT bump
  soccerdata itself**.
- Confirmed 1.9.0 is the current PyPI release. No maintainer patch since
  S19 for the rosters `AttributeError`.
- Per user preference: **skip the per-match try/except workaround for
  now.** 9/10 coverage stays as shippable. GER 2024-25 stays at 0 rows.
- Sub-dep refresh kept (security-relevant bumps in certifi/idna/requests
  etc.); committed at S20 close as part of routine refresh.

### Scope expansion: CL/EL/Conference + internationals + WC qualifiers

User reframed S20 to also cover the new ingest scope. Probed FBref +
ESPN + WhoScored:

- **Off-the-shelf coverage is tiny.** FBref + WhoScored expose Euro +
  WC + Women's WC by default; ESPN exposes only Big-5 domestic. The
  "soccerdata covers it" assumption was wrong.
- **`available_leagues()` is a curated default subset**, not the source's
  full capability. soccerdata supports overlaying additional leagues via
  `~/soccerdata/config/league_dict.json`, merged into
  `_config.py:LEAGUE_DICT` at import time.

### ✅ Path A proven end-to-end for CL via FBref

Phase 2a probe (after one wrong-string iteration corrected via the FBref
catalog dump):

- Overlay merge fires: `FBref.available_leagues()` returns 10 entries
  including `'UEFA-Champions League'`.
- `FBref(leagues=['UEFA-Champions League'], seasons='2024-2025')
  .read_schedule()` returned **189 rows** for CL 2024-25 (new
  league-phase format). MultiIndex `['league', 'season', 'game']` —
  **same shape as Understat**, so loader code reuse is real.
- Season returned as `'2425'` — same `SEASON_DB_TO_SD` map as Understat.

### FBref catalog inventory (S20 scope availability)

Probe dump of `/en/comps/` (158 competitions across 9 tables) confirmed
**every** competition in our S20 scope is on FBref:

| Scope | FBref `competition_name` |
|---|---|
| UEFA CL | `UEFA Champions League` |
| UEFA EL | `UEFA Europa League` |
| UEFA Conference | `UEFA Conference League` |
| Intl friendlies (M) | `International Friendlies (M)` |
| AFCON | `Africa Cup of Nations` |
| Copa América | `CONMEBOL Copa América` |
| Gold Cup | `CONCACAF Gold Cup` |
| Asian Cup | `AFC Asian Cup` |
| UEFA Nations League | `UEFA Nations League` |
| Euro (already default) | `UEFA European Football Championship` |
| WC (already default) | `FIFA World Cup` |
| WC Qual ×6 | `FIFA World Cup Qualification — <CAF\|CONCACAF\|CONMEBOL\|OFC\|UEFA\|AFC>` |
| WC Qual play-offs | `FIFA World Cup Qualification — Inter-confederation play-offs` |
| Bonus: FIFA Club WC 2025 | `FIFA Club World Cup` |
| Bonus club continental | `Copa Libertadores de América`, `Copa CONMEBOL Sudamericana`, `CONCACAF Champions Cup` |

**Em-dash gotcha banked in Claude.md:** WCQ names use `—` (U+2014), not
hyphen. Wrong byte → silent empty df → `pd.concat([])` ValueError.

### Schema deltas (FBref vs Understat) — design-doc fodder for S21

CL 2024-25 schedule sample showed:

1. `score` is text (`'9–2'`, em-dash separator) — loader needs parsing
   into `home_goals` / `away_goals`. Understat shipped these as separate
   numeric columns.
2. `game_id` is a hash string (`'7c5c2955'`), not Understat's integer.
   Our `games.game_id` is currently INTEGER → **schema migration likely
   needed** (INTEGER → VARCHAR). Verify against `db_schema.md` in S21.
3. `round` carries the knockout/league-phase label directly
   (`'League phase'`, `'Round of 16'`, `'Final'`). Solves "what stage is
   this match?" with no derivation.
4. `venue` is stadium name. Combined with `round`, gives automatic
   neutral-venue detection for finals.
5. `match_report` is FBref's URL slug; one HTTP fetch per match for the
   per-match endpoints.
6. **No xG in schedule** (vs Understat). Presumably in team-match
   endpoint; **unprobed** — S21 step 2.
7. `time` sometimes `'20:00 (21:00)'` (local + UTC). Parseable but
   quirky.

**Rate-limit cost banking:** FBref enforces 7s between requests
(`fbref.py:97 self.rate_limit = 7`). CL season per-match sweep ≈
**22 min wall** for player_match_stats. Multiply by all competitions ×
seasons. Cacheable; one-time-ish.

### Path B parallel (research-only; not committed to)

Fallbacks if Path A breaks on a specific competition:

- **statsbombpy** free open data: WC 2022, Euro 2024, Copa 2024, women's
  tournaments. Narrow but high quality.
- **api-football** (RapidAPI, ~$15/mo): broad coverage.
- **football-data.org** paid tier (~€15/mo): CL/EL/intl.

## Active task at S21 start: continue competition ingest design

Sequenced from where S20 closed:

1. **Commit overlay to repo + setup script.**
   - Add `data/config/league_dict.json` with at minimum the CL entry
     (and add others as we expand).
   - Add `src/tools/setup_soccerdata_overlay.py` that copies in-repo
     overlay → `~/soccerdata/config/league_dict.json`.
   - Reason: currently the overlay only lives on Indraneel's machine.
     Not reproducible on a fresh checkout.
2. **Probe FBref `read_team_match_stats` + `read_player_match_stats`
   for CL** — learn column shape before designing the loader.
   Rate-limited; single season only.
3. **Schema delta design** (write decisions, then code):
   - `game_id` type change (INTEGER → VARCHAR).
   - `score` parsing.
   - `round` / `venue` semantics.
   - Two-leg / neutral-venue handling.
   - League-string naming convention (`UEFA-*`, `INT-*`, `CONMEBOL-*`,
     `AFC-*`, `CAF-*`, `CONCACAF-*`, `OFC-*`).
4. **`docs/v104_ingest_competitions.md`** design doc capturing source
   decisions, league_dict extensions, cross-source `player_id` strategy
   (FBref IDs ≠ Understat IDs), all of (3).
5. **Schema migration code** per S17 rules (separate transactions, no
   FK-blocked alters, app-code enforcement where needed).
6. **`ingest_fbref.py`** loader — mirrors `ingest_understat.py`
   structure but handles FBref shape (score parsing, hash game_id,
   round/venue/aggregate).
7. Then sweep CL → EL → Conference → Continental (Copa/AFCON/Asian/Gold)
   → Nations League → WC Qualifiers ×6 → Friendlies. Each step its own
   probe + load + validate.

S20 left this at step 0 (Path A confirmed). S21 picks up at step 1.

## Deferred

- **Commit S20 work** — see "Commit message" at end.
- GER-Bundesliga 2024-25 (soccerdata upgrade exhausted; per-match
  workaround skipped per S20 user call).
- Probe files committed in S20 for next-session reference; **delete
  once `docs/v104_ingest_competitions.md` lands** (S18 pattern):
  - `src/load/v2_ingest/_probe_competitions.py`
  - `src/load/v2_ingest/_probe_cl_path_a.py`
  - `src/load/v2_ingest/_probe_fbref_catalog.py`
- `~/soccerdata/config/league_dict.json` in-repo copy + setup script
  (S21 step 1).
- Regenerate `docs/db_schema.md` after any further league adds.
- `derived_state_freshness` table + `check_freshness.py` tool.
- soccerdata column-reference doc + pre-flight checklist (carry-forward
  from S15).
- Recompute `player_season_stats` for newly-loaded leagues.

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
- `effective_position` extraction to `_position_policy.py`; V1.03
  stays untouched.
- New-league fallback (decision (a)): sub-only players in fresh
  leagues land on `'Sub'`.
- `players` dimension maintenance lives inside Section B.

From S19:
- Validation script as the standard post-load eyeball.
- 9/10 coverage with one known gap is an acceptable shippable state.

From S20:
- **soccerdata's `league_dict.json` overlay is the standard path** to
  extend coverage to arbitrary FBref competitions. Merged on top of
  `_config.py:LEAGUE_DICT` at import.
- Default `available_leagues()` is a curated subset (5–9 per scraper),
  not the source's full capability.
- **Path A (overlay) > Path B (alternative library / paid API)** for
  our scope. Path B retained as fallback for individual failures.
- FBref `competition_name` strings must match **exactly**, including
  em-dash characters.
- "Quick fix" budget for upgrade-style escapes: cap at the cheapest
  attempt (≤5 min); skip workaround if not resolved; bank as known gap.

## Commit message (for S20 close)

```
S20: Path A probes — FBref overlay confirmed for CL; routine dep refresh

- Confirmed soccerdata 1.9.0 is latest on PyPI; uv add --upgrade bumped
  18 sub-deps but not soccerdata. GER-Bundesliga 2024-25 fix attempt
  exhausted; staying at 9/10 coverage.
- Discovered new ingest scope (CL/EL/Conference/Continental/WCQ/
  Friendlies) not in Understat. Probed FBref + ESPN + WhoScored:
  default coverage is just Euro + WC.
- Phase 2a probes added under src/load/v2_ingest/ (deletable after
  docs/v104_ingest_competitions.md lands):
    - _probe_competitions.py    — available_leagues() per scraper
    - _probe_fbref_catalog.py   — full /en/comps/ enumeration
    - _probe_cl_path_a.py       — overlay merge + read_schedule for CL
- Confirmed end-to-end: FBref returns 189 rows for CL 2024-25 with our
  custom overlay. Path A viable for all S20-scope competitions.
- Out-of-repo state: ~/soccerdata/config/league_dict.json contains
  UEFA-Champions League overlay. In-repo copy + setup script is
  S21 step 1.
- Docs: session_state.md updated for S20; Claude.md banks FRA 305/306
  quirk, soccerdata overlay mechanism, em-dash gotcha, and the
  S20–S22 session-length rule trial.

Refs: docs/session_state.md
```

## References

- soccerdata GitHub: https://github.com/probberechts/soccerdata
- soccerdata issue tracker (filter "understat"):
  https://github.com/probberechts/soccerdata/issues
- Related but distinct failure mode (KeyError 'statData'):
  https://github.com/probberechts/soccerdata/issues/904
- soccerdata docs (Understat scraper):
  https://soccerdata.readthedocs.io/en/stable/reference/understat.html
- FBref's competition catalog (full): `~/soccerdata/data/FBref/leagues.html`
  cached locally — 158 competitions across 9 tables.
- soccerdata's overlay logic:
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/_config.py:184–193`
- soccerdata's FBref lookup:
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/fbref.py:145–188`
- FBref competition index page: https://fbref.com/en/comps/
- statsbombpy open data: https://github.com/statsbomb/open-data
