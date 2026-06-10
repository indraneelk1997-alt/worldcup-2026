# V1.04 competitions / internationals ingest — design

**Status**: Path A (FBref via overlay) chosen for shape + counting stats.
Path C (StatsBomb Open Data) chosen separately for select international
tournaments where xG matters. **Free-only path; paid sources parked.**
**Designed in**: S20 (catalog + Path A confirmation), S21 (probes,
Track B research, industry-shift discovery).
**Implements**: extend V1.04 source-centric ingest to non-Understat
competitions.
**Supersedes**: nothing. `ingest_understat.py` remains in place for
top-5 domestic leagues.

## Critical context (S21 finding): FBref / Opta data termination

On **January 20, 2026**, Sports Reference (FBref's parent) lost its
data partnership with Opta/StatsPerform. All advanced statistics were
removed from FBref output industry-wide:

- `xG`, `npxG`, `xAG`, `npxAG`, expected-goals-against
- Progressive passes, shot-creating actions, goal-creating actions
- Advanced defensive metrics

This is **not** a soccerdata bug — soccerdata is parsing what FBref
serves; FBref no longer serves it. Our existing Understat-loaded data
is unaffected (Understat runs its own xG model independent of Opta).

Sources:
- [The IX Sports — FBref's loss of advanced stats](https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/)
- [Ricardo Heredia — Farewell FBref Advanced Stats](https://ricardoheredia.substack.com/p/farewell-fbref-advanced-stats-when)
- [RedCafe.net thread](https://www.redcafe.net/threads/fbref-opta-pull-data-support.491087/)

## Scope

Per `(competition, season)`, ingest:

- `games`              — schedule + result
- `player_match_stats` — per-player per-match
- `team_match_stats`   — per-team per-match (FBref returns natively
                         per-team-per-match; no melt needed)

S21 target: **UCL only** via Path A. Pattern then mechanical to extend.

## Source decisions

### Free-only strategy — what each source actually gives us

| Source | We get | We don't get |
|---|---|---|
| **Understat** (already loaded via `ingest_understat.py`) | Top-5 domestic + xG | UCL, EL, internationals, friendlies, qualifiers |
| **FBref via soccerdata overlay** (Path A, this design) | Schedule, goals, lineups, formations, cards, fouls, round, venue, attendance for arbitrary FBref competitions | xG and advanced metrics (gone industry-wide since Jan 2026) |
| **StatsBomb Open Data** (Path C, separate S23+ track) | Event-level data with xG (+ 360 spatial on most) for ~6 major tournaments | Current UCL/EL/Conference/qualifiers/friendlies |

xG coverage under this strategy: top-5 domestic (Understat) + WC 2022 /
Euro 2024 / Copa 2024 / AFCON 2023 (StatsBomb). **No xG for UCL, EL,
Conference, AFCON 2025, Asian Cup 2024, Gold Cup 2025, Nations League,
WC Qualifiers (6 confeds), or international friendlies.** Documented
gap accepted at S21.

### Path A (chosen): FBref via `league_dict.json` overlay

soccerdata reads `~/soccerdata/config/league_dict.json` at import and
merges it onto `_config.py:LEAGUE_DICT` (lines 184–193). Adding entries
unlocks the FBref scraper for arbitrary competitions whose FBref
`competition_name` we know.

In-repo overlay: `data/config/league_dict.json`. Installed by
`src/tools/setup_soccerdata_overlay.py` — merge-with-backup, in-repo
wins on conflict, idempotent.

S21 overlay state: **UCL only** (`UEFA-Champions League`). UEL + UECL
+ continentals + WCQ + friendlies added incrementally, each after its
own empirical probe ("pay your probe rent" rule).

### Path C (chosen for select tournaments, deferred to S23+)

StatsBomb Open Data is free, full event-level + 360 spatial, no auth.
Use case: post-tournament xG and shot-location data for major
internationals already in our scope. Library: `statsbombpy`.

Confirmed current coverage (from competitions.json, S21 fetch):

| Tournament | Season(s) | 360 data? |
|---|---|---|
| FIFA World Cup | 2022 ✅, 2018, plus historical (1990, 1986, 1974, 1970, 1962, 1958) | 2022 yes |
| UEFA Euro | 2024 ✅, 2020 | 2024 yes |
| Copa América | 2024 ✅ | no |
| Africa Cup of Nations | 2023 ✅ | yes |

NOT covered for our scope:
- UCL latest = 2018/19 (all 18 listed seasons are historical)
- Europa League only 1988/89
- No Conference League
- No current domestic seasons (2024-25, 2025-26)
- No WCQ, friendlies, Nations League
- AFCON 2025, Asian Cup 2024, Gold Cup 2025 not present in checked portion

S23+ task: build `ingest_statsbomb.py` to load event-level data into a
sidecar schema (event-level data is much richer than per-match
aggregates — likely doesn't fit `player_match_stats` shape).

### Path B (paid) banked, deferred

- `api-football` (RapidAPI, ~$19/mo Pro tier): broad coverage including
  UCL xG, but xG availability is "inconsistent" per their docs — verify
  per-competition before committing.
- Sportmonks paid xG add-on: enterprise-priced.
- `football-data.org` paid tier: ~€15/mo, narrower than api-football.
- FotMob via `fotmob-api` (free, unofficial): library last released
  v1.0.0 in Feb 2024, 5 stars, 14 total commits — almost certainly
  broken in June 2026 given FotMob's evolving anti-scraping. Skip
  unless we want to maintain it ourselves.

Revisit paid only if modeling actively needs xG for non-Understat /
non-StatsBomb competitions.

## soccerdata behaviour — gotchas to design around (S20 + S21 findings)

### ✅ `read_schedule` is clean

Returns per-match rows with proper `league`/`season` MultiIndex. UCL
2024-25 returned 189 rows (S20 Phase 2a). Use directly for the `games`
table. Columns: `round`, `week`, `day`, `date`, `time`, `home_team`,
`score`, `away_team`, `attendance`, `venue`, `referee`, `match_report`,
`notes`, `game_id`.

### ⚠️ `read_team_match_stats` is all-comps contaminated

soccerdata constructs `/matchlogs/all_comps/<stat_type>/` URLs
(`fbref.py:415, 432`) for every team in `read_team_season_stats()`.
That endpoint returns each team's matches **across every competition
they played**, not just the configured league. The `league` index
level comes back as `<NA>`.

S21 Phase 2b probe: UCL config returned **1,121 rows** (vs ~378
expected), with EFL Cup matches mixed in.

**Loader filter strategy** (to land in the loader, not soccerdata):

- **Primary filter**: `match_report` URL substring (`Champions-League`).
  Most reliable — encoded by FBref's own URL slug generator.
- **Secondary cross-check**: `round` value ∈ `{'League phase',
  'Knockout phase play-offs', 'Round of 16', 'Quarter-finals',
  'Semi-finals', 'Final'}`. Catches edge cases.
- **Both** as defensive double-check; fail loudly if they disagree
  (signals FBref naming drift).

Loader explicitly assigns `league = 'UEFA-Champions League'` after
filter. The S18 "Option C" passthrough+assertion pattern from
`ingest_understat.md` does **not** apply for FBref team_match.

### ✅ `read_player_match_stats` is clean per match

soccerdata fetches `/en/matches/<game_id>/` once per match
(`fbref.py:762`). Each match belongs to exactly one competition, so
the result is comp-clean. The function inherits `league`/`season`/
`game` from `read_schedule()` and assigns them to each row
(`fbref.py:781–783`).

S21 Phase 2c probe (UCL 2024-25, `stat_type='summary'`):
- 5,826 rows (189 games × ~31 player-rows avg)
- 878 distinct players
- league = `'UEFA-Champions League'` ✅
- Wall time: **4,187s (≈70 min)** — 3× the 22-min estimate. Bank for
  capacity planning.

### `_parse_table` doesn't filter columns

soccerdata's `_parse_table` (`fbref.py:1037–1064`) just removes some
span icons and spacer rows, then calls `pd.read_html`. No column
dropping. So when the Expected subgroup is missing, it's because
FBref didn't serve it — not because soccerdata stripped it. (S21
post-mortem of the xG hunt.)

### Stat_type availability matrix (POST Jan 2026 FBref/Opta termination)

| Endpoint | Stat_types soccerdata exposes | What FBref serves today |
|---|---|---|
| `read_team_match_stats` | `schedule` (default), `shooting`, `keeper`, `misc` | Standard subgroup only — Expected/xG removed |
| `read_player_match_stats` | `summary` (default), `keepers` | Performance subgroup only — Expected/xG removed |

The 4 player-match stat_types that exist in FBref HTML but soccerdata
doesn't expose (`passing`, `defense`, `possession`, `misc`) — unclear
post-termination whether their tables still carry useful content
beyond what's in `summary`. Not probed; defer to S22+ if modeling
needs anything beyond the Performance counting stats.

## Schema deltas (FBref vs Understat) — to resolve in S22 step 3

- **`game_id`**: FBref returns hash strings (e.g., `'7c5c2955'`), not
  Understat's integer. Our `games.game_id` is currently INTEGER →
  schema migration likely needed (INTEGER → VARCHAR). Per S17 rules:
  ALTER blocked on FK-referenced tables; may need table-recreate.
- **`score`**: FBref returns text (`'9–2'` with en-dash). Loader must
  parse into `home_goals` / `away_goals`.
- **`round`**: NEW signal — knockout/league-phase label directly in
  the data. Worth adding as a `round` column on `games`.
- **`venue`**: stadium name. Combined with `round`, gives automatic
  neutral-venue detection for finals.
- **`Formation` / `Opp Formation` / `Captain`**: bonus columns from
  team_match. Worth capturing.
- **Multi-position `pos`**: FBref returns `'DF,MF'` etc. (vs
  Understat's single value). The S18 `effective_position` policy needs
  adapting.
- **`age` as `'30-246'` text** (years-days). Loader parsing needed.
- **MultiIndex columns** from FBref endpoints. Loader flattens.
- **Cross-source `player_id`**: FBref player IDs ≠ Understat player
  IDs. Recommend **defer entirely** (option c) — load FBref data clean
  with FBref-native IDs, build a crosswalk only when actually needed
  for cross-source aggregation. Same physical Mbappé in PL (Understat)
  + UCL (FBref) → two `players` rows; downstream join on
  `(name, dob, nationality)` when required.
- **`team_match_stats` shape**: FBref returns one row per team per
  match natively (after our all-comps filter). The S18 per-game
  home/away unpivot trick is NOT needed for FBref.

## League naming convention

Canonical league_dict keys align with soccerdata's existing
`<CONFED-OR-COUNTRY>-<COMPETITION>` style. Filename / variable / probe
references use the short abbreviation.

| Comp | Abbrev | Canonical key | Source plan |
|---|---|---|---|
| UEFA Champions League | UCL | `UEFA-Champions League` | FBref (no xG) |
| UEFA Europa League | UEL | `UEFA-Europa League` | FBref (no xG) |
| UEFA Conference League | UECL | `UEFA-Conference League` | FBref (no xG) |
| UEFA Nations League | UNL | `UEFA-Nations League` | FBref (no xG) |
| UEFA European Championship | EURO | `INT-European Championship` (default) | FBref + StatsBomb for 2024 |
| FIFA World Cup | WC | `INT-World Cup` (default) | FBref + StatsBomb for 2022 |
| WC Qual UEFA | WCQ-UEFA | TBD (FBref: `FIFA World Cup Qualification — UEFA`) | FBref (no xG) |
| WC Qual CONMEBOL/CONCACAF/CAF/AFC/OFC | WCQ-{conf} | TBD | FBref (no xG) |
| Africa Cup of Nations | AFCON | TBD | FBref + StatsBomb for 2023 |
| Copa América | COPA | TBD | FBref + StatsBomb for 2024 |
| AFC Asian Cup | AFC-AC | TBD | FBref (no xG) |
| CONCACAF Gold Cup | GOLD | TBD | FBref (no xG) |
| International Friendlies (M) | INTL-FR | TBD | FBref (no xG) |

Em-dash gotcha (Claude.md): all WCQ entries use `—` U+2014, not hyphen.

## Loader interface (planned)

```
uv run python src/load/v2_ingest/ingest_fbref.py \
    --league "UEFA-Champions League" \
    --season "2024-2025"
```

Same shape as `ingest_understat.py`. Internal differences (per above):
score parsing, hash game_id, all-comps team_match filter + explicit
league assignment, MultiIndex flattening, multi-position handling.
No xG ingestion (none to ingest).

## Test plan

1. ✅ S20: Phase 2a probe — UCL schedule reachable, 189 rows.
2. ✅ S21: Phase 2b probe — team_match schedule shape, contamination
   confirmed (1,121 rows including EFL Cup).
3. ✅ S21: Phase 2c probe — team_match shooting (no xG), player_match
   summary (5,826 rows, no xG). Root cause: FBref/Opta termination.
4. ✅ S21: Track B research — StatsBomb / FotMob / api-football
   feasibility checked. Free-only path adopted.
5. S22 step 3: schema delta finalization (game_id type, score parse,
   round, venue, multi-pos, age, MultiIndex flatten).
6. S22 step 5: schema migration code per S17 rules.
7. S22 step 6: build `ingest_fbref.py`.
8. S22 step 7: dry-run UCL 2024-25, eyeball ~189 games / ~378
   team_match / ~5826 player_match rows after filter.
9. S22 step 8: live UCL 2024-25 load.
10. S22 step 9: re-run `validate_v104_ingest.py`; expect 10/10 → 11/11
    once UCL added (still excluding GER 24-25 unless re-attempted).
11. S22 step 10: live UCL 2025-26 load.
12. S23+: replicate pattern for UEL, UECL, Continental cups, WCQ,
    friendlies. Open separate `ingest_statsbomb.py` track for event-
    level WC/Euro/Copa/AFCON xG.

## References

- soccerdata FBref source:
  `~/worldcup-2026/.venv/lib/python3.12/site-packages/soccerdata/fbref.py`.
  Key lines: 145–188 (`read_leagues`), 339–467
  (`read_team_match_stats`), 703–807 (`read_player_match_stats`),
  1037–1064 (`_parse_table`).
- soccerdata custom league overlay logic: `_config.py:184–193`.
- FBref per-match page structure (POST Jan 2026): per-team
  `stats_<team_id>_summary` (Performance group only — Expected gone),
  `keeper_stats_<team_id>`. Other stat_types unverified post-termination.
- V1.04 source-centric ingest design: `docs/v104_ingest_design.md`.
- V1.04 Understat ingest precedent: `docs/v104_ingest_understat.md`.
- S20 catalog probe: 158 FBref competitions across 9 tables
  (`src/load/v2_ingest/_probe_fbref_catalog.py`).
- S20 Phase 2a probe (UCL schedule): 189 rows
  (`src/load/v2_ingest/_probe_cl_path_a.py`).
- S21 Phase 2b probe (UCL team_match schedule): 1,121 rows / all-comps
  contamination (`src/load/v2_ingest/_probe_UCL_team_player_shapes.py`).
- S21 Phase 2c probe (UCL shooting + summary): 1,121 / 5,826 rows
  (`src/load/v2_ingest/_probe_UCL_team_player_extended.py`).
- StatsBomb Open Data:
  https://github.com/statsbomb/open-data,
  competitions.json verified S21.
- StatsBombPy library: https://github.com/statsbomb/statsbombpy.
- FBref/Opta termination news (Jan 20, 2026):
  https://www.theixsports.com/the-ix-soccer/fbrefs-loss-advanced-stats-womens-soccer-data-accessibility/
