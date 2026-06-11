# Session State

> **Fast-changing.** This is "where we are right now." Updated at the end
> of each working session. For permanent facts/rules, see `Claude.md`.

**Last updated:** end of S25 (2026-06-11)
**Current version line:** StatsBomb Open sidecar built + **Euro 2024 loaded**
(event + 360). FBref club comps cover UCL+UEL+UECL (both seasons); WC2026
squad + EA FC 26 prior (S23). DB **33 base tables** (+2 views); `players`
7537 (dob 4070 = 54%, untouched — sidecar is self-contained). Next: load the
other 3 StatsBomb tournaments, then re-measure coverage + resolver.

## S25 outcome — StatsBomb Open sidecar designed + Euro 2024 loaded

Design-led session, then the build. Shell-relay throughout (rule 12).
Full design in `docs/statsbomb_ingest_design.md` (D1–D3b, all observe-driven).

### Observed (verified S25 via `sb.competitions()`, not inferred)
- `statsbombpy` 1.19.0 added via `uv add` (→ `pyproject.toml` + `uv.lock`
  changed). Open-data tier emits a benign `NoAuthWarning` per call.
- The four targets by **composite `(competition_id, season_id)`** (season_id
  is NOT unique alone — Euro24 & Copa24 both 282): **WC22 (43,106) +360 ·
  Euro24 (55,282) +360 · Copa24 (223,282) NO 360 · AFCON23 (1267,107) +360.**
- `sb.frames()` df path is broken (`InvalidIndexError`) → always use
  `fmt='dict'`. Events `fmt='dict'` = lossless nested (the `raw` source).
  Full-360 frames are anonymized (no player_id); per-shot `shot_freeze_frame`
  is named + lives inside `statsbomb_event.raw`.

### Built (all applied + verified)
- **`migrate_statsbomb_schema.py`** — 4 NEW sidecar tables, additive,
  idempotent. Dry-run **compiles every DDL in-memory** (rule 4) before apply;
  native `JSON` type confirmed on this build; `index`→`event_index` (reserved).
  Self-contained on StatsBomb's ID space → **zero links into players/games**,
  no FK-block exposure. No declared FKs inside the sidecar (app-enforced,
  mirrors `wc2026_squad.our_player_id`).
- **`ingest_statsbomb.py --tournament {wc2022,euro2024,copa2024,afcon2023}`**
  (`--apply`/`--limit`). Per-match `INSERT OR IGNORE` (bounded memory),
  hybrid typed-cols + `raw` JSON built from one `fmt='dict'` pass.
- **Euro 2024 loaded:** `statsbomb_match` 51 · `statsbomb_event` 187924 ·
  `statsbomb_frame` 2698999 · `statsbomb_frame_meta` 164530 · 1340 shots
  w/ xG · 495 distinct StatsBomb player_ids · comp/season `(55,282)`.
  **Orphan checks 0** (frame→event, event→match). `json_extract` round-trip
  on `raw` confirmed (top xG goals render correctly). Idempotent re-run safe.
- DB base tables 29 → **33** (+`statsbomb_match/event/frame/frame_meta`).

### S26 openers (clean)
1. **Load the other 3 tournaments** — same loader, just `--tournament wc2022`
   / `copa2024` / `afcon2023` (copa2024 has NO 360 → frame tables stay empty
   for it, by design). Each ~similar scale; WC22 is the big one.
2. **Re-measure coverage** — re-run `_probe_resolver_overlap.py`; StatsBomb's
   495 intl players (×4 tournaments) should shrink the 247-strong dark set.
3. **Then the resolver** (`statsbomb_player_id`/`wc2026_squad` xref), then
   coverage score, then EA-empirical blend. Dashboard still S26+ (Streamlit).

### Owed housekeeping (surface, schedule when convenient)
- Regenerate `docs/db_schema.md` (now DUE — 4 new tables); included in the
  S25 commit block below.
- Add a `validate_v104_ingest.py`-style section (or a small
  `validate_statsbomb.py`) for the sidecar — the orphan/count checks ran
  inline this session but aren't yet a committed validator.
- Still owed from S24: `validate_v104_ingest.py` for UEL/UECL + UCL 25-26;
  soften "~100% EA attribute baseline" in `analysis_pipeline_design.md`;
  delete spent probes (`_probe_resolver_overlap.py` — keep until coverage
  re-measure, `_probe_uel_uecl_schedules.py`, `_probe_wc2026_squads.py`,
  `_probe_nation_codes.py`).
- Cosmetic: silence `NoAuthWarning` in `ingest_statsbomb.py` (snippet noted
  in S25 chat) next time the file is touched.

### S25 commit (run after regenerating db_schema.md)
```
S25: StatsBomb Open sidecar — design + Euro 2024 loaded (event + 360)

New self-contained sidecar (own ID space, zero links into players/games):
statsbomb_match/event/frame/frame_meta. Raw events stored (typed cols +
raw JSON), aggregation deferred downstream. Euro 2024 fully loaded:
51 matches / 187924 events / 2.7M frame rows / 1340 shots w/ xG; orphans 0.

New:  docs/statsbomb_ingest_design.md
      src/load/v2_ingest/migrate_statsbomb_schema.py
      src/load/v2_ingest/ingest_statsbomb.py
Updated: docs/session_state.md, docs/db_schema.md (33 tables),
         pyproject.toml + uv.lock (statsbombpy 1.19.0)

Refs: docs/statsbomb_ingest_design.md, docs/session_state.md
```

## S24 outcome — UEL + UECL loaded; resolver overlap measured (then parked)

Continued the data-acquisition track (sequencing: gather → THEN coverage →
THEN resolver/blend). Shell-relay workflow throughout (rule 12).

### Loaded — UEFA Europa League + Conference League, both seasons
- Overlay extended: `data/config/league_dict.json` +`UEFA-Europa League`
  (FBref `"UEFA Europa League"`) +`UEFA-Conference League` (FBref
  `"UEFA Conference League"` — NOT "Europa Conference", verified vs cached
  catalog). Re-ran `setup_soccerdata_overlay.py` (3 entries now).
- Probe `_probe_uel_uecl_schedules.py` confirmed columns identical to UCL →
  `ingest_fbref.py` reused with **zero code changes**.
- Fetched both leagues in **parallel** (2 background dry-runs, read-only →
  coexist; ~2h wall), then **4 applies sequentially** (game_id minting reads
  committed max, so sequential = collision-free; ids now 10000378–10001061).
  Applied: UEL 24-25 (189g/5851pm/911pl), UEL 25-26 (189/5899/921), UECL
  24-25 (153/4718/880), UECL 25-26 (153/4736/889). All guards passed; UECL
  lost 7 pm rows to PK INSERT-OR-IGNORE dedup (benign).
- Totals: FBref games 1062 (378 UCL + 378 UEL + 306 UECL). `players` 4880→
  **7537**, with_dob 1415→**4070 (54%)**. db_schema.md regenerated (29 tables).

### Resolver overlap measured — then PARKED (premature until StatsBomb)
`_probe_resolver_overlap.py` (uncommitted, S24) sized squad↔EA / squad↔players
match BEFORE the StatsBomb load. Key finding (banked, revisit post-StatsBomb):
- **EA is NOT a ~100% baseline** — only 68% (850/1247) of squad players match
  EA by exact name; ~247 genuinely absent, concentrated in **whole dark
  squads** (Qatar 26, Jordan 25, Iran 25, Uzbekistan 24, S.Africa/Egypt 21…)
  — Gulf/Asian/African domestic leagues EA + our club data both miss.
- Coverage matrix (exact name_norm): both=536, EA-only=314, empirical-only=32,
  **neither(dark)=365**. EA ambiguity trivial (9, split by club+age).
  Empirical: 568 any, 277 dob-confirmed, 244 name-only ambiguous.
- **Owed doc fix:** soften the "~100% attribute baseline" claim in
  `analysis_pipeline_design.md` (the locked *philosophy* holds; the number is
  wrong). StatsBomb (intl tournaments) is expected to materially shrink the
  dark set — that's WHY resolver/coverage waits for it.

### S25 openers
1. **StatsBomb Open ingest** (`ingest_statsbomb.py`, statsbombpy) — event +
   360 for WC22/Euro24/Copa24/AFCON23. New sidecar schema. The real new build.
2. Then re-measure coverage (re-run `_probe_resolver_overlap.py`), THEN build
   the resolver (`wc2026_squad.ea_id` + `our_player_id`), THEN coverage score.
3. Housekeeping: `validate_v104_ingest.py` for UEL/UECL + UCL 25-26; delete
   probes; commit S24.

## S23 outcome — dashboard/analysis track opened; UCL 25-26 + squad + EA loaded

Design + build session. Shell was unavailable to the assistant the whole
session (WSL UNC mount error) → **new workflow (Claude.md rule 12): assistant
hands copy-paste bash blocks, Indraneel runs them + pastes output.** Worked
well. Read-only DB reads + dry-runs done concurrently with the live fetch.

### Data loaded (all applied + verified)
- **UCL 2025-26** via `ingest_fbref.py --season 2025-2026 --apply` (dry-run
  cached first, ~off-cache apply). 189 games / 378 team_match_fbref / 5850
  player_match_fbref. Player resolver: 341 reused + 537 newly minted, 0
  rough-merges. `players` now **4880** (was 4343), **with_dob 1415** (was 878).
  ⚠️ owed: `validate_v104_ingest.py` Section 10 not re-run for 25-26 (apply's
  inline guards passed: 378==2×189, score xcheck, FK orphans 0).
- **`wc2026_squad`** (new table) via `ingest_wc2026_squads.py --apply`:
  1247 players / 48 nations / 48 captains. Idempotent re-run = 0 inserts
  (natural-key UNIQUE confirmed; nextval PK confirmed).
- **`ea_fc26_player`** (16228 men) + **`ea_fc26_playstyle`** (15032) via
  `ingest_ea_fc26.py --apply`. INSERT BY NAME + float→int coercion confirmed.
- `db_schema.md` regenerated → **29 tables**.

### New files (S23, uncommitted)
- `docs/analysis_pipeline_design.md` (spine; S22-close), `docs/data_sourcing.md`
  (items a + b fully designed), `data/config/nation_codes.json` (48 WC nations
  → FIFA-3, validated).
- `src/load/v2_ingest/ingest_wc2026_squads.py`, `ingest_ea_fc26.py`.
- `src/load/v2_ingest/_probe_wc2026_squads.py`, `_probe_nation_codes.py`
  (probes — **now deletable**).
- `notebooks/explore_worldcup.ipynb` (DB explorer, read-only short-lived conns),
  `notebooks/explore_ea_fc26.ipynb` (EA CSV explorer).
- EA Kaggle CSVs under `data/raw/eafc26/` (flynn28 = anchor; talha = backup).
- Claude.md: rule 11 (S20-22 trial) **sunset**; rule 12 (shell-relay) added.

### Key decisions banked (don't relitigate)
- Squad source = **Wikipedia** "2026 FIFA World Cup squads" (only free source
  with the full link key name+nation+dob+club in one parse; 48×~26=1247).
- Nations parse from `<h3>` (groups are `<h2>`); accept a wikitable only if
  cols == the 7-field squad schema (drops summary tables). DoB needs dateutil
  (page mixes 'May 17, 2000' US + '8 October 1997' intl formats).
- Matching model = **candidate-by-`name_norm`, then disambiguate by what each
  candidate carries** (dob for FBref subset / club-alias+league for Understat
  subset). Our `players` is thin (id,name,dob); 80% dob-NULL + Understat has
  NO nation. Club too noisy → tiebreaker only.
- EA anchor = **flynn28 EAFC26.csv** (has PlayStyles + GK + OVR; talha lacks
  them). Filter GENDER='M'. 6 family scores `ea_`-prefixed (collide with sub
  -attrs). PlayStyle tiers = base/plus only (no ++). EA nation spellings differ
  ('Holland','Korea Republic') → reconcile in resolver, nation_code NULL for now.
- **Sequencing (agreed):** gather data → decide paid → THEN coverage (item c)
  → THEN EA-empirical blend/shrinkage. Don't fit coverage to a moving footprint.

### S24 openers (clean)
1. **EA↔squad / squad↔players resolver** — fill `wc2026_squad.ea_id` +
   `our_player_id` + `link_method`/`link_confidence`. Needs EA-nation alias
   (Holland→NED…) + club alias map. The first real coverage signal.
2. Then continue data acquisition (international-first: WCQ/friendlies/NL/
   continental; UEL/UECL; StatsBomb Open) — scoped by the squad roster.
3. Coverage score (item c) + EA-empirical blend — AFTER acquisition.
4. Housekeeping owed: `validate_v104_ingest.py` for UCL 25-26; delete probes;
   **commit S22 + S23** (S22 still unpushed: origin/main=c9b4ff0, HEAD=c6f69b3).

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

## S22 outcome — schema delta design LOCKED (step 3 complete)

Design-only session, no code, no live DB writes. All eight schema
deltas decided one-at-a-time; deliverables written:
`docs/v104_ingest_competitions.md` "Schema deltas — RESOLVED S22 step
3" + new `docs/v104_schema_migration.md` (migration plan + DDL sketch).

**Governing architecture: Option C — source-separated FBref fact
tables.** FBref per-match data → new `team_match_fbref` /
`player_match_fbref`; Understat fact tables untouched; 3 shared
dimensions (`games`, `players`, `positions`) take additive changes
only; cross-source via union views. Migration is **pure additive**
(ADD COLUMN / INSERT / CREATE) — sidesteps every DuckDB FK-block gotcha.

Decisions (detail in the two docs):
- (a) `game_id` stays INTEGER + surrogate (≥10M) for FBref + new
  `source`/`source_game_id` — **pushed back on VARCHAR recreate**.
- (b) `games.stage` + `games.venue` (VARCHAR NULL; `stage` not `round`
  — ROUND() clash).
- (c) score → `home_goals/away_goals/home_pens/away_pens` on `games`,
  parsed loader-side; validator cross-check. Understat backfill
  deferred to one post-gather shot.
- (d) multi-pos: source-aware `_position_policy.py` + coarse
  `DF/MF/FW` codes in `positions`; primary-token wins.
- (e) age → `players.player_dob` (back-computed, validated).
- (f) MultiIndex flatten helper + curated `FBREF_COL_MAP`
  anti-corruption layer, **fail loud on unmapped**.
- (g) all-comps filter **inverted**: `read_schedule` game_id
  membership = primary; URL-slug + round enum = fail-loud secondary.
- (h) Option C source-separated tables (above).

**⚠️ Shell was unavailable this whole session** (UNC mount error — bash
could not start). State was verified via the pasted
`validate_v104_ingest.py` output only: 9/10 Understat confirmed, DB
grand totals identical to the 2026-06-05 `db_schema.md` dump (→ DB
untouched since S21). **Still NOT verified (owed next session):**
`git log`/`git status` (HEAD `c9b4ff0`? 5 ahead? clean tree?), and
whether the soccerdata package / `league_dict.json` overlay moved.
These are **pre-flight gate 1** in `v104_schema_migration.md` and must
pass before any migration statement runs.

## S22 implementation — UCL 2024-25 loaded end-to-end (steps 4–8 done)

Pre-flight gates all passed (git HEAD c9b4ff0 confirmed — note: repo was
already pushed, origin/main == HEAD, NOT 5-ahead as prior state said;
DB untouched; observe-probes run). Then, observing-before-coding, two
design-doc premises were corrected against real data (S14 lesson):

- **Score shootout format is `(N) R–R (N)`** (e.g. `(1) 0–1 (4)` = reg
  0–1, pens 1–4), NOT the doc's guessed `1 (4)`. Also `team_match`
  GF/GA carry the same parens (`'1 (2)'`) — parse leading int.
- **Player-match `pos` is a MIX**: granular (CB/LB/DM…, already in our
  vocab) + coarse (DF/MF/FW) + multi (`DF,MF`) + `AM` (= our CAM). The
  doc's "all coarse `DF,MF`" was the season-pos, not match-pos.

New empirical findings banked:
- **FBref `read_player_match_stats` exposes player NAME, no numeric id.**
  → mint surrogate player_ids (base 50_000_000).
- **Player dob drifts ±1–2 days across a player's matches** (FBref age
  rounding). So the surrogate key is `(norm_name, nation)`, with a
  **canonical dob = modal derived dob** stored on `players`. Keying on
  exact dob over-split 878 players into 1163 — caught in dry-run.
- **`team_match` exposes no game_id** → parse 8-char hash from
  `match_report` URL; filter by membership in the clean `read_schedule`
  set (decision g primary).
- **`position_id` is Understat-native** (a source column, not derived);
  FBref has none → `player_match_fbref.position_id` left NULL, link via
  `effective_position` → `positions.position_code`. Vestigial column;
  drop in a later cleanup migration if desired.
- season comes back `'2425'` (mapped to `'2024-2025'`, reused Understat
  SEASON map).

Build status (active task step list):
1. ✅ Commit overlay + setup script (S21).
2. ✅ Probe team_match + player_match shapes for UCL (S21).
3. ✅ Schema delta design — LOCKED (S22).
4. ✅ **Migration applied** — `migrate_v104_fbref_schema.py` (additive,
   idempotent, dry-run/--apply). games +8 cols, players +player_dob,
   positions +DF/MF/FW, +team_match_fbref / player_match_fbref tables,
   +team_match_all / player_match_all views.
5. ✅ **`ingest_fbref.py` built** — Sections A (schedule→games) / B
   (team_match→team_match_fbref) / C (player_match→players +
   player_match_fbref). `_position_policy.py` extended source-aware
   (`fbref_effective_position`, AM→CAM, primary-token). Dry-run/--apply.
6. ✅ Dry-run UCL 2024-25 — eyeballed 189 / 378 / 5826, all guards pass.
7. ✅ **Live load UCL 2024-25** — 189 games, 378 team, 878 players,
   5826 player_match. Idempotent re-run confirmed (0 new).
8. ✅ **`validate_v104_ingest.py` extended** (Section 10, Option C) +
   run clean: invariant 378==2×189, score cross-check 0 mismatch, all
   FK orphans 0, dob 878/878.
9. ⬜ **Live load UCL 2025-26** — NEXT. NOT cached → ~70-min live
   rate-limited fetch (`read_player_match_stats`). Same command,
   `--season 2025-2026`. Run in a dedicated/background session.
10. ⬜ Then replicate the pattern for UEL/UECL/continentals/WCQ/friendlies.
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
- **Commit S22 work** — docs (`v104_ingest_competitions.md` updated,
  `v104_schema_migration.md` new, this file) AND code
  (`migrate_v104_fbref_schema.py`, `ingest_fbref.py`,
  `_position_policy.py` FBref extension, `validate_v104_ingest.py`
  Section 10). NOTE: migration already APPLIED to the live DB; backups
  at `worldcup.duckdb.s22-bak` (pre-migration) and
  `worldcup.duckdb.s22-preload-bak` (post-migration, pre-FBref-load).
- **Understat `games` goals backfill** — populate
  `home_goals/away_goals` (+pens NULL) for the 3,198 existing rows from
  `team_match_stats`, in one shot once all sources are gathered
  (decision c).
- GER-Bundesliga 2024-25 (soccerdata upgrade exhausted at S20).
- **Probe files — now deletable** (`ingest_fbref.py` has landed):
  - `src/load/v2_ingest/_probe_UCL_team_player_shapes.py` (S21)
  - `src/load/v2_ingest/_probe_UCL_team_player_extended.py` (S21)
  - `src/load/v2_ingest/_probe_s22_schema_shapes.py` (S22)
  - `src/load/v2_ingest/_probe_s22_pos_coverage.py` (S22)
  - (S20-era probes too)
- **Regenerate `docs/db_schema.md` — now DUE** (migration applied +
  UCL loaded): `uv run python src/tools/dump_db_schema.py`.
- **`player_match_fbref.position_id`** — vestigial NULL column
  (Understat-only field); optional later cleanup-migration to drop it.
- `derived_state_freshness` table + `check_freshness.py` tool.
- Recompute `player_season_stats` for newly-loaded leagues.
- Re-run paid-API check (api-football, Sportmonks) if modeling needs
  xG for non-Understat / non-StatsBomb comps.
- StatsBomb Open Data ingest track (S23+).
- **S23 DASHBOARD + ANALYSIS track** — see new
  `docs/analysis_pipeline_design.md` (agreed S22-close): Streamlit
  dashboard (locked), pipeline = player Att/Mid/Def attributes → zonal
  "chessboard" battles (xT-grounded) + playstyle modifiers → team
  xScoreline → sim. Data: international-first (FBref WCQ/friendlies/
  intl) + StatsBomb Open (spatial validation) + **EA Sports FC 26 attrs
  via Kaggle CSV** (coverage solver / informative prior; NOT SoFIFA —
  Cloudflare-blocked) + optional cheap paid API. Per-player coverage =
  a feature + shrinkage weight. Full S23 pickup prompt in S22-close chat.

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

From S22 (schema delta design):
- **Option C (source-separated FBref fact tables)** is the integration
  architecture — don't weld shape-only FBref rows into xG-dense
  Understat tables. Understat fact tables stay untouched.
- **Surrogate `game_id`, not VARCHAR** — never recreate FK-referenced
  fact tables when an additive surrogate path exists. The "no xG" gap
  is structural; let the schema show it (separate tables), don't hide
  it as NULLs.
- Migration is additive-only by construction → no DuckDB FK-block
  gotchas in play.
- Loader carries all parsing (surrogate id, schedule-membership filter,
  score parse, MultiIndex flatten + fail-loud map, source-aware
  position policy, age→DOB). `FBREF_COL_MAP` fail-loud is the
  FBref-drift early-warning.
- Name `stage` not `round` (DuckDB `ROUND()` clash).

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
