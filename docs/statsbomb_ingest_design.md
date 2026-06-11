# StatsBomb Open ingest — design

**Status:** living design doc, started S25 (2026-06-11). Companion to
`docs/analysis_pipeline_design.md` (the why) and `docs/data_sourcing.md`
(per-source ingest decisions). This doc = the StatsBomb Open sidecar
schema + loader decisions. Design captured one decision at a time;
nothing here is coded yet unless marked ✅.

StatsBomb Open is **not just another source** — per
`analysis_pipeline_design.md` it is the **spatial validation set** for the
stage-2 chessboard (formation→zone occupancy priors checked against real
touch/action locations) AND the international-tournament coverage that our
club (FBref/Understat) + EA data miss for "dark" national-team players.

- Library: `statsbombpy` 1.19.0 (`uv add statsbombpy`, S25).
  GitHub: https://github.com/statsbombpy/statsbombpy /
  https://github.com/statsbomb/statsbombpy
- Open data repo: https://github.com/statsbomb/open-data
- Access: open-data only (no credentials) → `sb.competitions()` etc. emit a
  `NoAuthWarning: credentials were not supplied. open data access only`.
  Expected and benign.

## Observed catalog facts (verified S25 via `sb.competitions()`, not inferred)

`sb.competitions()` → 80 rows × 12 cols. Key cols:
`competition_id, season_id, country_name, competition_name,
competition_gender, competition_youth, competition_international,
season_name, match_updated, match_updated_360, match_available_360,
match_available`.

### The four target tournaments

| Tournament | `competition_id` | `season_id` | 360 frames? |
|---|---|---|---|
| FIFA World Cup 2022 | 43 | 106 | ✅ yes (`match_available_360` set) |
| UEFA Euro 2024 | 55 | 282 | ✅ yes |
| Copa América 2024 | 223 | 282 | ❌ **none** (`match_available_360` = NaN) |
| African Cup of Nations 2023 | 1267 | 107 | ✅ yes |

Two findings that shape the schema:

1. **Copa 2024 is events-only (no 360).** Matches the honest matrix in
   `session_state.md` (Copa listed as event-level, not +360). The sidecar
   must NOT assume 360 exists for every tournament — 360 is an optional
   per-match/per-tournament layer, joined on, never required.
2. **`season_id` is not unique on its own.** Euro 2024 and Copa 2024 are
   both `season_id=282` (different `competition_id`); WC 2022 (43/106)
   collides on `season_id=106` with Women's Euro 2022 (53/106). →
   **the StatsBomb natural key is the composite `(competition_id,
   season_id)`** everywhere. Never key on `season_id` alone.

(Also noted: a name-substring filter for "Africa Cup" misses StatsBomb's
"African Cup of Nations" string — `competition_id=1267`. Pull these four by
their observed `(competition_id, season_id)` pairs, not by name matching.)

## Decision log

### D1 — Granularity: store RAW EVENTS, aggregate downstream — ✅ LOCKED (S25)

Store one row per StatsBomb event (the source truth); compute zone
occupancy / xT / any grid-based aggregate **downstream**, when the
chessboard model exists. Rejected: pre-aggregating to a player×zone grid at
ingest (B), and shots-only (C).

Rationale (grounded in locked project principles):
- **"Don't fit to a moving footprint"** (sequencing rule, `data_sourcing.md`):
  the chessboard zone grid (16×12? Juego half-space lanes?) doesn't exist
  yet. Aggregating at ingest bakes an undecided grid into stored data and,
  having discarded the events, forces a full re-fetch to re-grid. Raw store
  → re-aggregate for free.
- **StatsBomb is the spatial validation set** (`analysis_pipeline_design.md`):
  it needs *all* touch/action locations, not just shots. Shots-only (C)
  discards the spatial occupancy that is the whole reason StatsBomb is in
  scope.
- **Extends Option C source-separation**: StatsBomb gets its own sidecar
  tables, never welded into FBref/Understat fact tables. Raw events *are*
  the validation truth ("observe, don't infer" applied to storage).
- **Size is a non-issue**: DuckDB is a columnar analytical engine built for
  this scan workload; four tournaments ≈ a few hundred thousand event rows.
  https://duckdb.org/why_duckdb

Cost accepted: the event table is wide + heterogeneous, and StatsBomb's
ID space is disjoint from ours → linking is its own decision (D2).

### D2 — Linking + separation: self-contained sidecar, resolver-later — ✅ LOCKED (S25)

The sidecar lives entirely on **StatsBomb's own ID space**; it makes **zero
links into `games` / `players` at ingest**. Rejected: minting StatsBomb
players into `players` / matches into `games` (B).

- `statsbomb_match` dimension (one row per match: `match_id`,
  `competition_id`, `season_id`, date, home/away team id+name, score,
  stage). Cheap tournament/stage/score anchor.
- Event + 360 facts reference `statsbomb_match.match_id`; carry StatsBomb
  `player_id`/name + `team_id`/name **denormalized exactly as the source
  provides** (no separate `statsbomb_player` dim yet — don't over-normalize
  before we need it; resolver collects distinct player ids later).
- Cross-walk to our universe (`statsbomb_player_id → players.player_id` /
  `wc2026_squad.squad_row_id`) is a **separate, re-runnable, confidence-
  scored resolver mapping table**, built in the deferred resolver step —
  **never at ingest**. Mirrors the working `wc2026_squad.our_player_id` /
  `ea_id` pattern.

Rationale:
- **Sequencing is locked** — resolver comes *after* StatsBomb load. B would
  force name-matching at ingest (the premature coupling the rule forbids).
- **Claude.md FK gotchas** — `players` is heavily FK-referenced and DuckDB
  can't drop/re-add constraints. A never touches it; B risks the FK-block
  pain.
- **Option C, taken further** — separate source → separate tables →
  separate ID space. Cleanest separation from FBref/Understat facts.
- **Provenance** — store StatsBomb ids verbatim; resolve explicitly later.

### D3 — Event-table column strategy + 360 handling — ✅ LOCKED (S25, principle)

**Hybrid: curated typed columns + a `raw` JSON fidelity column.** Rejected:
fully-relational (~100 sparse columns, brittle to StatsBomb drift).

- Promote pipeline-queried fields to clean typed columns: event `id`,
  `match_id`, period/minute/second, `type`, team id+name, player id+name,
  `position`, `x`/`y` (split from the `location` list), `end_x`/`end_y`,
  `outcome`, `shot_xg`, `body_part`, `play_pattern`, `under_pressure`.
- Keep the **entire original event as a `raw` JSON column** → lossless +
  drift-proof; un-promoted fields recoverable later via DuckDB
  `json_extract`, no re-fetch. https://duckdb.org/docs/data/json/overview
- Whether statsbombpy's flattened row is truly lossless vs raw open-data
  JSON = a **pilot check**, not an assumption.

**360 frames → their own sparse table `statsbomb_frame`** (one row per
event×player-in-frame: `x`/`y` + teammate/actor/keeper flags, keyed to the
event). Only exists for WC22 / Euro24 / AFCON23 (not Copa24) → optional
join, never required.

**Sidecar table set:** `statsbomb_match` (dim) · `statsbomb_event` (curated
+ `raw` JSON) · `statsbomb_frame` (360, sparse). Resolver xref table built
later (D2).

**Exact curated column list = finalized at the Euro 2024 pilot** against a
real `events()` dataframe (D3b), before any DDL.

### D3b — Exact columns (Euro 2024 pilot, match_id 3930158) — match+event ✅, frame ⚠️

Pilot observed (S25): `matches(55,282)` = 51×55 cols; `events(3930158)` =
3372 rows × **89 sparse cols**; `events(..., fmt="dict")` = lossless nested
raw; `frames()` **errored** (see below).

Confirmed against real data:
- Events DO carry ids: `player_id`, `team_id`, `possession_team_id`,
  `pass_recipient_id` → D2 denormalization is sound.
- `location` = `[x,y]` list; end-locations are type-specific
  (`pass_end_location`/`carry_end_location`/`shot_end_location`, last may be
  `[x,y,z]`). xG col = **`shot_statsbomb_xg`**.
- `fmt="dict"` → full nested original per event = the lossless `raw` source.
- `shot_freeze_frame` is embedded in `events()` → per-shot 360 needs no
  separate fetch.

**`statsbomb_match`** (dim, PK `match_id`): `match_id`, `competition_id`,
`season_id`, `match_date`, `kick_off`, `match_week`, `competition_stage_id`,
`competition_stage`, `home_team_id`, `home_team`, `away_team_id`,
`away_team`, `home_score`, `away_score`, `stadium_id`, `stadium`,
`referee_id`, `referee`, `ingested_at`. (Managers/country meta left in an
optional `raw` JSON if wanted; not promoted for v1.)

**`statsbomb_event`** (fact, PK `id` uuid, FK `match_id`): `id`, `match_id`,
`index`, `period`, `timestamp`, `minute`, `second`, `type`, `possession`,
`possession_team`, `possession_team_id`, `team_id`, `team`, `player_id`,
`player`, `position`, `play_pattern`, `x`, `y` (split from `location`),
`end_x`, `end_y` (coalesced from the type-specific end-location),
`duration`, `outcome` (coalesced `*_outcome`), `body_part` (coalesced),
`under_pressure`, `pass_recipient_id`, `shot_xg` (`shot_statsbomb_xg`),
`raw` JSON (full event dict — everything else recoverable via
`json_extract`). Build typed cols + `raw` from the `fmt="dict"` pass.

**`statsbomb_frame`** (360, sparse) — ✅ via the **dict path**.
`sb.frames(3930158)` (df path) raises `InvalidIndexError` (statsbombpy/pandas
normalizer quirk, not ours), but **`sb.frames(mid, fmt="dict")` works** →
list of 3090 records, each `{event_uuid, visible_area, match_id,
freeze_frame:[{teammate, actor, keeper, location:[x,y]}]}`. The loader
fetches dict + normalizes itself (consistent with "store raw, normalize
downstream"; sidesteps the broken df path).

Two grains observed:
- **Full 360 is anonymized** — positions + `teammate/actor/keeper` flags,
  **no player_id**. Fine: it's occupancy truth for chessboard validation,
  not player attribution.
- **Per-shot `shot_freeze_frame`** (in `events()`) is **named** (player
  id+position) but shot-moments only — already inside `statsbomb_event.raw`,
  so **no separate named-frame table needed**.

Tables:
- `statsbomb_frame` (event×actor grain, FK `event_uuid`→`statsbomb_event.id`):
  `event_uuid`, `match_id`, `frame_idx`, `x`, `y`, `teammate`, `actor`,
  `keeper`. The exploded spatial-occupancy validation set.
- `statsbomb_frame_meta` (per-event): `event_uuid`, `match_id`,
  `visible_area` JSON. Small; lets us later know which zones the camera
  actually observed (avoids treating off-camera as empty).

### Loader note (downstream asset, not design-blocking)
`Starting XI` (2/match) + `Tactical Shift` (4/match) events carry
`tactics.formation` + full `tactics.lineup` (player id+jersey+position) —
captured in `statsbomb_event.raw`. This is the per-match roster + formation
source the **resolver** (distinct StatsBomb player_id → ours) and the
formation-occupancy priors will mine downstream.

## Design status — ✅ COMPLETE (S25)

D1–D3b locked. Final sidecar: `statsbomb_match` · `statsbomb_event`
(typed + `raw` JSON) · `statsbomb_frame` · `statsbomb_frame_meta`. Resolver
xref table deferred to the resolver step. **Next: DDL / migration script**
(`migrate_statsbomb_schema.py`, additive + idempotent, dry-run/--apply),
then pilot-load Euro 2024 end-to-end before scaling to the other three.

## References

- statsbombpy: https://github.com/statsbomb/statsbombpy
- StatsBomb Open Data: https://github.com/statsbomb/open-data
- Expected Threat (xT, downstream consumer): https://karun.in/blog/expected-threat.html
- DuckDB analytical workload: https://duckdb.org/why_duckdb
