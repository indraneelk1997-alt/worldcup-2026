# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S21 (2026-06-10, late evening)
**Current version line:** V1.04 ingest — Understat 9/10 + FBref overlay
mechanism proven for UCL, schema/loader work pending S22

## Latest repo state (verify with `git log` / `git status` at session start)

- Branch: `main`. At S21 start, HEAD was `5e7ecdd S20: Path A probes —
  FBref overlay confirmed for CL; routine dep refresh` (clean tree).
- S21 close commit (intended): see "Commit message" below.
- **Out-of-repo state worth knowing:**
  `~/soccerdata/config/league_dict.json` overlay was rewritten this
  session — now matches the in-repo `data/config/league_dict.json`
  (UCL entry only, no WhoScored line, no unverified extras). `.bak` of
  S20-era version preserved adjacent.
- `~/soccerdata/data/FBref/` has substantial cache from this session:
  189 cached match HTMLs (`match_<id>.html`) for UCL 2024-25 plus
  matchlogs for 36 teams in schedule + shooting stat_types. ~10–20 MB
  on disk. Useful for any S22 re-probe — cache hits are instant.
- Verify before trusting: `git log --oneline -5` and
  `git status --short`. (Observe, don't infer.)

## S21 outcome — Path A confirmed; xG industry-shift discovered; free-only strategy chosen

### What we set out to do (per S20 close-out)

S21 step 1 (commit overlay + setup script), step 2 (probe FBref
team/player match shapes for UCL), step 3 (schema delta design),
step 5 (schema migration), step 6 (build `ingest_fbref.py`).

### What we actually did

Steps 1 + 2 only — step 2 took us much deeper than planned because we
discovered a real-world industry shift.

#### ✅ Step 1: overlay committed + setup script

- `data/config/league_dict.json` — in-repo canonical overlay,
  UCL only, no unverified WhoScored line.
- `src/tools/setup_soccerdata_overlay.py` — merges in-repo → user
  config, in-repo wins on conflict, `.bak` backup, idempotent. Verified
  via running and observing diff output (existing user file had a
  WhoScored line; backup made; correct merge).

#### ✅ Step 2 Phase 2b/2c probes done

Three probes; deletable in S22+ once `ingest_fbref.py` lands and the
design doc captures all findings (it does already):

- `src/load/v2_ingest/_probe_UCL_team_player_shapes.py` —
  `read_team_match_stats(stat_type='schedule')`. **1,121 rows** (vs
  ~378 expected for UCL alone): `all_comps` URL hardcoded in
  soccerdata returns each team's matches across every competition.
  `league` index = `<NA>`.
- `src/load/v2_ingest/_probe_UCL_team_player_extended.py` —
  `read_team_match_stats(stat_type='shooting')` + `read_player_match_stats(stat_type='summary')`.
  Step 1 (~6 min wall): same contamination, no xG. Step 2 (~70 min
  wall, vs 22-min estimate): 5,826 rows, 189 games, 878 distinct
  players, league correctly `'UEFA-Champions League'`. No xG.
- soccerdata source-read: `_parse_table` (`fbref.py:1037–1064`) does
  no column filtering; just runs `pd.read_html`. So if Expected
  subgroup is missing, FBref didn't serve it.

#### 🚨 xG investigation — root cause is industry-wide

Both probes returned **no Expected subgroup / no xG**. Three rounds
of diagnostics confirmed FBref's HTML doesn't carry xG-related
`data-stat` values for UCL anymore (137 comments in match HTML are
all short navigation remnants, no hidden xG tables).

Web search revealed the cause: **Jan 20, 2026 — Sports Reference lost
their data partnership with Opta/StatsPerform.** All advanced stats
removed from FBref output industry-wide (xG, npxG, xAG, progressive
passes, shot-creating actions, expected-goals-against). Banked
permanently in `Claude.md` + `docs/v104_ingest_competitions.md`.

Refs:
- https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/
- https://ricardoheredia.substack.com/p/farewell-fbref-advanced-stats-when

#### Track B research (alternative xG sources)

Investigation confirmed there is no single-source free replacement
for FBref's advanced stats. Findings:

- **StatsBomb Open Data** (free, event-level + 360 spatial): excellent
  for **WC 2022, Euro 2024, Copa 2024, AFCON 2023**. **NOT** for
  current UCL (latest = 2018/19), Europa League (only 1988/89),
  Conference, qualifiers, friendlies, Nations League, current
  domestic seasons. Useful as a separate S23+ track for the major
  intl tournaments we'd want xG on.
- **fotmob-api** (free unofficial library): last release Feb 2024,
  v1.0.0, 5 stars, 14 total commits, "ToDo!" documentation. ~24
  months stale vs FotMob's evolving anti-scraping. Almost certainly
  broken; skip unless we want to maintain ourselves.
- **api-football** (paid, ~$19/mo, RapidAPI): xG coverage is
  "inconsistent" per their own docs. Defer.
- **Sportmonks paid xG add-on / football-data.org paid tier**: defer.

User decision at S21 close: **free-only path; revisit paid only if
modeling actively needs xG for non-Understat/non-StatsBomb comps.**

#### xG coverage under free-only strategy (the honest matrix)

| Comp | xG source | xG available? |
|---|---|---|
| Top-5 domestic 2024-25, 2025-26 | Understat (already loaded) | ✅ |
| WC 2022 | StatsBomb (S23+) | ✅ event-level + 360 |
| Euro 2024 | StatsBomb (S23+) | ✅ event-level + 360 |
| Copa 2024 | StatsBomb (S23+) | ✅ event-level |
| AFCON 2023 | StatsBomb (S23+) | ✅ event-level + 360 |
| UCL, UEL, Conference 2024-25 / 2025-26 | FBref via soccerdata | ❌ no xG |
| AFCON 2025, Asian Cup 2024, Gold Cup 2025 | FBref via soccerdata | ❌ no xG |
| WC Qualifiers 2026 (6 confeds) | FBref via soccerdata | ❌ no xG |
| UEFA Nations League | FBref via soccerdata | ❌ no xG |
| International friendlies | FBref via soccerdata | ❌ no xG |

Modeling implication: where we have xG (top-5 domestic + 4 intl
tournaments), use it. Elsewhere, lean on goals + shots + form +
lineups + formations + round + venue. Documented gap, not a bug.

### What we banked in Claude.md

- Jan 2026 FBref/Opta termination + xG sourcing implications.
- soccerdata's `read_team_match_stats` all-comps contamination.
- soccerdata's `_parse_table` is just `pd.read_html` — doesn't filter
  columns; missing columns mean FBref didn't serve them.
- 22-min estimate vs 70-min observed wall-time for one UCL season of
  per-match player stats. Capacity-planning fact.
- In-repo overlay + setup-script pattern.

## Active task at S22 start: continue UCL loader (Path A, no xG)

S21 left us at step 2 done. S22 picks up at step 3:

1. ✅ Commit overlay + setup script (S21).
2. ✅ Probe team_match + player_match shapes for UCL (S21).
3. **Schema delta design** (S22 start):
   - `game_id` type change INTEGER → VARCHAR (FK-blocked ALTER per S17
     — investigate if table-recreate dance is needed).
   - `score` parsing into `home_goals` / `away_goals`.
   - `round` + `venue` columns on `games`.
   - Multi-position `pos` handling (`'DF,MF'` style).
   - `age` text parsing (`'30-246'` format).
   - MultiIndex column flattening for FBref output.
   - All-comps team_match filter strategy (URL substring + round enum
     cross-check) — code in loader, not config.
   - Cross-source `player_id` strategy — defer entirely (option c per
     v104_ingest_competitions.md).
4. **Schema migration code** (S22) per S17 rules.
5. **Build `ingest_fbref.py`** (S22).
6. **Dry-run UCL 2024-25** — eyeball ~189 games / ~378 team_match
   after filter / ~5,826 player_match rows.
7. **Live UCL 2024-25 load**.
8. **Re-run `validate_v104_ingest.py`** — expect 10/11 (10 Understat +
   1 UCL); still excluding GER 24-25 unless re-attempted.
9. **Live UCL 2025-26 load**.

Then S23+: replicate pattern for UEL, UECL, Continental, WCQ,
Friendlies. Open separate `ingest_statsbomb.py` track for event-
level WC/Euro/Copa/AFCON xG.

## Deferred

- **Commit S21 work** — see "Commit message" at end.
- GER-Bundesliga 2024-25 (soccerdata upgrade exhausted at S20).
- **Probe files** committed in S21 for reference; **delete once
  `ingest_fbref.py` lands** (S22 step 5):
  - `src/load/v2_ingest/_probe_UCL_team_player_shapes.py`
  - `src/load/v2_ingest/_probe_UCL_team_player_extended.py`
  - (S20-era probes already in repo can also be cleaned then)
- Regenerate `docs/db_schema.md` after schema migration + first load.
- `derived_state_freshness` table + `check_freshness.py` tool.
- Recompute `player_season_stats` for newly-loaded leagues.
- Re-run paid-API check (api-football, Sportmonks) if modeling needs
  xG for non-Understat / non-StatsBomb comps.
- StatsBomb Open Data ingest track (S23+).

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
- Option C (passthrough + assertion) — does NOT apply for FBref
  team_match (S21: league is `<NA>`).
- `effective_position` policy at `_position_policy.py`; needs
  extension for FBref multi-position `'DF,MF'` shape (S22).
- New-league fallback (decision (a)): sub-only players land on `'Sub'`.
- `players` dimension maintenance inside Section B.

From S19:
- Validation script as the standard post-load eyeball.
- 9/10 coverage with one known gap is shippable.

From S20:
- soccerdata's `league_dict.json` overlay is canonical extension path.
- Default `available_leagues()` is curated subset, not source capability.
- Path A (overlay) > Path B (alternative library / paid).
- FBref `competition_name` strings must match exactly (em-dash gotcha).
- "Quick fix" budget: cap at cheapest attempt; skip workaround if not
  resolved; bank as known gap.

From S21:
- **Jan 2026 FBref/Opta termination** is a permanent industry fact.
  xG missing from FBref output is not a bug.
- **Free-only path accepted** for non-Understat / non-StatsBomb comps,
  no xG. Document, don't hide.
- **StatsBomb is a separate later track** for major intl tournaments
  (event-level data) — different schema, different loader.
- soccerdata's `read_team_match_stats` is all-comps contaminated;
  filter strategy lives in loader (URL substring + round enum cross-check).
- soccerdata's `_parse_table` doesn't filter columns — missing columns
  reflect what FBref serves, nothing more.
- Cross-source `player_id` strategy: defer entirely (option c).

## Commit message (for S21 close)

```
S21: FBref overlay for UCL committed; Path A probes done; xG gap acknowledged

Path A (FBref via soccerdata overlay) confirmed end-to-end for UCL via
empirical probes. In-repo overlay + setup script committed. xG turned
out to be unavailable via FBref industry-wide as of Jan 2026 — banked
as known constraint and accepted; free-only path adopted with documented
gaps for UCL/EL/Conference/qualifiers/friendlies. StatsBomb deferred as
separate S23+ track for major intl tournaments.

New files:
  data/config/league_dict.json
  src/tools/setup_soccerdata_overlay.py
  src/load/v2_ingest/_probe_UCL_team_player_shapes.py
  src/load/v2_ingest/_probe_UCL_team_player_extended.py
  docs/v104_ingest_competitions.md

Updated:
  Claude.md           (FBref/Opta termination, soccerdata gotchas,
                       in-repo overlay pattern, 70-min wall observation)
  docs/session_state.md  (S21 close)

Phase 2c probe findings:
  read_team_match_stats stat_type='schedule' for UCL → 1121 rows
    (all_comps URL contamination; EFL Cup etc mixed in; league=<NA>).
  read_team_match_stats stat_type='shooting' for UCL → 1121 rows,
    Standard subgroup only (no Expected/xG — Jan 2026 termination).
  read_player_match_stats stat_type='summary' for UCL → 5826 rows
    across 189 games / 878 players; Performance subgroup only;
    league correctly tagged 'UEFA-Champions League'.
  Wall time observed: ~70 min for one UCL season (vs 22-min estimate).

S22 picks up at schema delta design (step 3 of active task).

Refs: docs/v104_ingest_competitions.md, docs/session_state.md
```

## References

- soccerdata GitHub: https://github.com/probberechts/soccerdata
- soccerdata FBref module:
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/fbref.py`
  Key lines: 145–188 (`read_leagues`), 339–467 (`read_team_match_stats`),
  703–807 (`read_player_match_stats`), 1037–1064 (`_parse_table`).
- soccerdata custom overlay logic: `_config.py:184–193`.
- FBref/Opta termination (Jan 20, 2026):
  https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/
  https://ricardoheredia.substack.com/p/farewell-fbref-advanced-stats-when
- StatsBomb Open Data: https://github.com/statsbomb/open-data
  competitions.json verified S21.
- StatsBombPy: https://github.com/statsbomb/statsbombpy
- fotmob-api (likely broken): https://github.com/C-Roensholt/fotmob-api
- api-football pricing: https://www.api-football.com/pricing
- FBref competition catalog (cached): `~/soccerdata/data/FBref/leagues.html`
  158 competitions across 9 tables.
- Related Understat parser issue (still open, distinct from S21
  findings): https://github.com/probberechts/soccerdata/issues/904
