# Data sourcing — dashboard + analysis track (S23+)

**Status:** living doc, started S23 (2026-06-11). Companion to
`docs/analysis_pipeline_design.md` (the why) and `docs/dashboard_design.md`
(the surfaces). This doc = per-source ingest decisions for the new track.
Design captured one decision at a time; nothing here is coded yet unless
marked ✅.

Source order of battle (from `analysis_pipeline_design.md`): WC2026 squad
anchor → EA FC 26 attribute prior → coverage map → StatsBomb Open spatial
validation → semantic/metrics layer. This doc fills in as we go.

## Sequencing — revised S23 (agreed)

**Gather the data *before* defining coverage + shrinkage.** A coverage
score and an EA-vs-empirical blend formula fit to today's footprint would
need recalibration the moment we add UCL 25-26 / UEL / the international
layer / any paid feed. So the order is:

1. **Acquire** — finish the ingest backlog, *scope-bounded to WC2026 squad
   needs* (international-first; club comps only where squad players play):
   UCL 2025-26 (ready, ~70-min live FBref), then UEL/UECL + continental
   (AFCON/Asian Cup/Gold Cup/Copa/Euro) + WCQ ×6 + Nations League +
   friendlies; StatsBomb Open spatial set (WC22/Euro24/Copa24/AFCON23).
2. **Decide paid** — only after web-verifying per-comp xG coverage for the
   actual squads' leagues; pay only if modelling needs xG we can't get free.
3. **THEN coverage** (item c) — measured against the real, final footprint.
4. **THEN shrinkage / EA-empirical blend** — weighted by that coverage.
5. Chessboard + dashboard surfaces consume the above.

Guardrail: FBref serves ~158 comps — do **not** fetch all. The squad roster
(item a) drives which leagues/clubs are worth pulling. Items (c) + blend
formula are explicitly **deferred** to after step 2.

---

## (a) WC2026 squad ingest — ✅ BUILT + APPLIED S23

> Status: `ingest_wc2026_squads.py` live-loaded `wc2026_squad` (1247 players,
> 48 nations, idempotent re-run = 0). nation_codes.json validated. Resolver
> (our_player_id / ea_id) is S24. Design below is as-built.

### Decision: source = **English Wikipedia "2026 FIFA World Cup squads"**

`https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads`

**Why Wikipedia over the alternatives (both sides):**

| Source | For | Against | Verdict |
|---|---|---|---|
| **Wikipedia** | One page, all 48 teams, clean per-team wikitable. **Carries our entire link key** (name, dob, club) + coarse pos + caps/goals + captain. Final squads already locked (announced May 27–31 2026). Free, no auth, re-fetchable. | Community-maintained (not de jure official); club/name spellings are English-press variants; shirt numbers often blank pre-tournament. | **CHOSEN** — it is the only free source that hands us the full join key in one parse. |
| FIFA.com official | De jure authoritative squad lists. | JS-rendered, no clean table endpoint, harder to scrape; no dob/club in a parseable grid. Anti-bot risk. | Use only as a **cross-check** on player *membership* if a squad looks wrong. |
| Paid API (Sportmonks / api-football) squad endpoint | Structured JSON, stable ids. | Costs money for a **one-time, 48×26 ≈ 1,250-row** static pull we only need once. IDs don't match ours anyway. | **Rejected for squads** — disproportionate. (Still on the table later for *club xG*, item TBD.)

> Pushback note: paying an API for ~1,250 static rows we fetch once is the
> wrong tool. Wikipedia gives the same fields with richer link metadata
> (dob+club) for free. Reserve any paid spend for the xG gap, where it
> actually buys something we can't get free.

**Observed page facts (verified S23, not inferred — fetched the live page):**
- Header confirms: 48 teams, squads of up to 26 (3 GK). Age stated as of
  June 11 2026. **Club = "the club for which the player last played a
  competitive match prior to the tournament"** — i.e. current club. Good.
- Per-team table columns: `No. | Pos. | Player | Date of birth (age) |
  Caps | Goals | Club`.
- `Pos.` is **coarse only** (GK/DF/MF/FW) — *not* our granular vocab
  (CB/LB/DM/CAM…). Maps cleanly onto `positions.position_class`
  (GK/DEF/MID/FWD), not `position_code`.
- Captain marked inline in the Player cell: `Name (captain)`.
- `dob` is full and unambiguous (e.g. "May 17, 2000 (aged 26)") → parse to
  DATE, drop the "(aged NN)".
- Nation is the **section context** (team heading), not a table column —
  the parser must carry the current team down each row.

### Proposed squads dimension — `wc2026_squad` (additive, Option-C-friendly)

New standalone dimension; touches nothing existing (append-only posture,
Claude.md rule 9). Draft columns:

| Column | Type | Notes |
|---|---|---|
| `squad_row_id` | INTEGER PK | surrogate, our own sequence |
| `nation_name` | VARCHAR | Wikipedia heading, e.g. `'Czech Republic'` |
| `nation_code` | VARCHAR | 3-letter, joins to our match data — **needs a name→code map (see open Q2)** |
| `player_name` | VARCHAR | as printed (keep raw); plus a `name_norm` below |
| `name_norm` | VARCHAR | accent-stripped, lowercased — the fuzzy-join handle |
| `dob` | DATE | strong link key |
| `club` | VARCHAR | current club, English-press spelling |
| `position_class` | VARCHAR | GK/DEF/MID/FWD (map from GK/DF/MF/FW) |
| `shirt_no` | INTEGER NULL | usually blank pre-tournament |
| `caps` | INTEGER NULL | from table (context, not modelling) |
| `intl_goals` | INTEGER NULL | from table |
| `is_captain` | BOOLEAN | parsed from "(captain)" |
| `our_player_id` | INTEGER NULL | resolved link → `players.player_id`; **NULL = zero coverage** (expected, and a feature) |
| `link_method` | VARCHAR | `dob+name` / `name+club` / `name+nation` / `fuzzy` / `none` |
| `link_confidence` | DOUBLE NULL | 0–1, for the dashboard coverage badge |
| `source` | VARCHAR | `'wikipedia'` |
| `source_url` | VARCHAR | the page URL |
| `ingested_at` | TIMESTAMP | run stamp |

### Linking to our `players` — the real subtlety

Our `players` dimension is **thin**: `(player_id, player_name, player_dob)`
only (verified in fresh `db_schema.md`). There is **no nation or club on
`players`** — nation lives on `player_match_fbref.nation`, club = `team` on
the match tables. So the join key (name, nation, dob, club) is assembled
*across* tables, and two of its four fields are unevenly populated:

- **`player_dob` is only populated for FBref-loaded players** (UCL: 878).
  Understat top-5 players have `dob = NULL` (schema sample: De Bruyne dob
  None). So dob-keyed matching only works for the FBref subset.

**Our players split into two matchable shapes** (observed S23):

- **Subset A — FBref (878 players):** carry `player_dob` + `nation`
  (via `player_match_fbref`). Strong, unambiguous matching.
- **Subset B — Understat (3,465 players):** `player_dob` NULL **and no
  nation anywhere** (Understat tables have no nation column). Only name +
  club (`team`, Understat spelling) + league are available — and club
  drifts (Q3). Weak matching.

Because most of our base (the 80%) has neither dob nor nation, a fixed
"key ladder" is the wrong model. Use **candidate-generation, then
best-available disambiguation** — per Wikipedia squad row:

1. **Generate candidates** = our players where `name_norm` matches
   (`name_norm = lower(strip_accents(player_name))`, applied identically
   both sides — verified S23 it folds João→joao, Gündogan→gundogan).
2. **0 candidates →** `our_player_id = NULL`, `link_method='none'`. The
   *expected* outcome for many squad players; this is the coverage signal
   item (c) consumes. Never force a match.
3. **1 candidate →** link; `link_method='name'` (`link_confidence` lower
   if nothing else corroborates).
4. **>1 candidate → disambiguate by what each candidate carries:**
   - candidate in Subset A → compare Wikipedia `dob` to `player_dob`
     (`link_method='name+dob'`, highest confidence).
   - candidate in Subset B → compare Wikipedia `club` to the player's
     recent `team` **via the short-name alias map** + league
     (`link_method='name+club'`).
   - still tied → leave NULL + flag for manual review; don't guess.

**Side benefit:** once a Subset-B player is linked, Wikipedia's `dob` can
**backfill** our NULL `player_dob` (additive, optional) — turning the squad
ingest into a dob source for top-5 players we currently lack birthdates for.

**Residual risks → resolve at loader dry-run (not design-blocking):**
`name_norm` collision rate within our 4,343 players (how often step 4
fires), and Understat `team` spellings (dumped separately from the FBref
spellings in Q3) — the dry-run will print unmatched + ambiguous counts to
eyeball before any write.

Every link records `link_method` + `link_confidence` so the dashboard can
show *how* we know a player, and the predictor can shrink accordingly.

### Open questions — RESOLVED S23 (observed in WSL, not inferred)

- **Q1 ✅ git pre-flight.** HEAD = `c6f69b3` (S22 close), tree clean bar
  expected doc edits. Caveat: `origin/main` = `c9b4ff0` (S21) — S22 close
  committed **but not pushed** (1 ahead). Non-blocking; push when convenient.
- **Q2 ✅ nation codes = FIFA-style 3-letter** (`FRA ESP GER NED BRA ENG
  POR SUI CRO DEN…`), on `player_match_fbref.nation`. NOT full names, NOT
  IOC. → build a Wikipedia-name → FIFA-3 map for all 48 teams; validate
  overlap against this dump.
- **Q3 ✅ club drift is severe** → club **demoted from join key to
  tiebreaker.** Observed: we store soccerdata short names — `Dortmund`,
  `Leverkusen`, `Inter`, `Red Star`, `PSV`, `Sporting CP` — vs Wikipedia's
  fuller "Borussia Dortmund", "Bayer Leverkusen", "Inter Milan", "Crvena
  Zvezda", "PSV Eindhoven". A raw club equality join would mostly miss.
  Alias map only, and only as a name-collision tiebreaker.
- **Q4 ✅ dob is sparse + names are accented.** `with_dob = 878 / 4343`
  (20% — the FBref subset only); `accented_names = 829`. `strip_accents()`
  folds names cleanly. Consequence: the strong dob key reaches only 20% of
  our base → drives the candidate-generation matching model above, and the
  Subset A/B split. This was the pivotal finding of item (a).

### Locked DDL — `wc2026_squad` (design final S23; NOT yet applied)

Flat table chosen for v1 (team-level metadata like coach/group/confed can
be a `wc2026_team` parent later if the dashboard needs it — not now).
Additive + standalone → no DuckDB FK-block exposure. `our_player_id` is a
**plain column, app-enforced**, NOT a declared FK into `players` (keeps the
roster decoupled and avoids adding yet another dependency onto the already
heavily FK-referenced `players` table — Claude.md FK gotchas).

```sql
CREATE SEQUENCE IF NOT EXISTS seq_wc2026_squad_row START 1;

CREATE TABLE IF NOT EXISTS wc2026_squad (
  squad_row_id    INTEGER  PRIMARY KEY DEFAULT nextval('seq_wc2026_squad_row'),
  nation_name     VARCHAR  NOT NULL,          -- Wikipedia heading, e.g. 'Czech Republic'
  nation_code     VARCHAR,                    -- FIFA-3, app-enforced (name->code map)
  player_name     VARCHAR  NOT NULL,          -- raw as printed
  name_norm       VARCHAR  NOT NULL,          -- lower(strip_accents(player_name))
  dob             DATE,                        -- always present from Wikipedia
  club            VARCHAR,
  position_class  VARCHAR  NOT NULL,          -- GK/DEF/MID/FWD (from GK/DF/MF/FW)
  shirt_no        INTEGER,                     -- often NULL pre-tournament
  caps            INTEGER,
  intl_goals      INTEGER,
  is_captain      BOOLEAN  DEFAULT FALSE,
  our_player_id   INTEGER,                     -- -> players.player_id; NULL = no EMPIRICAL coverage
  link_method     VARCHAR,                     -- none/name/name+dob/name+club/manual
  link_confidence DOUBLE,
  ea_id           INTEGER,                     -- -> ea_fc26_player.ea_id; the EA PRIOR (see item b)
  ea_link_method  VARCHAR,                     -- none/name+nation/name+nation+club/manual
  ea_link_confidence DOUBLE,
  source          VARCHAR  DEFAULT 'wikipedia',
  source_url      VARCHAR,
  ingested_at     TIMESTAMP DEFAULT now(),
  UNIQUE (nation_name, name_norm, dob)         -- natural key -> INSERT OR IGNORE idempotency
);
```

Idempotent re-load via `INSERT OR IGNORE` on the natural key
`(nation_name, name_norm, dob)` — all three always present from the source,
so re-running the ingest can't duplicate a roster row. The `our_player_id`
/ `link_*` columns are populated by a **separate resolver pass** (re-runnable,
`UPDATE` by `squad_row_id`), so re-matching as our player coverage grows
never touches the roster rows themselves.

> ⚠️ Verify-on-apply (bash, later): `nextval` DEFAULT + table-level `UNIQUE`
> both need a quick dry-run on the live DuckDB — banked as a pre-apply check,
> not assumed working.

**Residual (loader dry-run, not design-blocking):** `name_norm` collision
rate within `players`; Understat `team` spellings. Parser mechanics
(`pandas.read_html` vs BeautifulSoup vs the already-fetched markdown)
decided alongside the EA FC parser in (b) for consistency.

---

## (b) EA FC 26 attribute ingest — ✅ BUILT + APPLIED S23

> Status: `ingest_ea_fc26.py` live-loaded `ea_fc26_player` (16228 men) +
> `ea_fc26_playstyle` (15032). nation_code deferred (NULL) to the resolver.
> Design below is as-built.

The **coverage solver / informative prior** (see `analysis_pipeline_design.md`).
EA rates ~16k men globally, so nearly every WC squad player gets a ready-made
attribute set even with zero empirical match data.

### Decision: anchor = **`flynn28/eafc26-player-database`, `EAFC26.csv`**

Two Kaggle datasets compared (observed S23, real columns — not inferred):

| Dataset | Cols | Has PlayStyles? | GK attrs? | OVR / alt-pos / weak-foot? | Verdict |
|---|---|---|---|---|---|
| **flynn28/eafc26-player-database** (`EAFC26.csv`) | 59 | ✅ `play style` w/ tiers | ✅ 5 GK | ✅ all | **CHOSEN** |
| talhademirezen/fc-26-player-stats | 47 | ❌ | ❌ | ❌ | rejected (clean numeric Height/Weight + full-word family names, but missing our core inputs) |

Both share EA's `ID` (Salah = 209331 in both) → talha is cross-linkable later
if we ever want its clean numerics; trivial to parse from flynn's strings anyway.

> Pushback note: talha is "cleaner" superficially but omits PlayStyles + GK +
> OVR — the exact fields the chessboard/attribute layers need. Cleanliness of
> two columns doesn't outweigh absence of three required features.

### Observed facts (verified S23)

- `EAFC26.csv` = **men + women combined** (17,873 = 16,228 M + 1,645 F) →
  **filter `GENDER='M'`** (16,228). Women out of scope (separate tournament).
- `ID` **unique** → clean PK. But **141 duplicate `Name`s** → EA→squad link
  needs nation to disambiguate, name alone won't do.
- Position vocab = 12 codes `{GK, CB, LB, RB, CDM, CM, CAM, LM, RM, LW, RW,
  ST}`, all map onto our 4 `position_class` buckets, no leftovers (mapping
  below).
- GK attrs (`GK Diving…`) populated **only for the 2,014 GKs** → nullable,
  GK-only. (Outfield sub-attrs assumed present for all; confirm at dry-run.)
- `play style` tiers observed = **base and `+` only** (no `++` in this scrape)
  → tier is a 2-value enum. 72 raw tokens fold to fewer base names once `+`
  is stripped.
- `Height`/`Weight` are strings (`"175cm / 5'9\""`, `"72kg / 159lb"`) → parse
  leading integer → `height_cm`, `weight_kg`.
- `Nation` is full-name (`'Egypt'`) → **reuse the same name→FIFA-3 map** as (a).
  `Team` is `'Liverpool'`, `'FC Barcelona'` → club drift, tiebreaker-only.
- EA gives **`Age` (int), not dob** → no dob key; EA age ≈ Wikipedia age
  (both as-of-2026) so age is a corroborator, not a key.

### Position map (EA code → our `position_class`)

`GK→GK` · `CB,LB,RB→DEF` · `CDM,CM,CAM,LM,RM→MID` · `LW,RW,ST→FWD`
(LW/RW→FWD is consistent with our existing RW=FWD precedent in
`player_season_stats`.)

### Locked schema — `ea_fc26_player` (one row per EA ID; NOT yet applied)

Load the **full men database** (~16,228), not just squad players — cheap, and
future-proofs opponent/club context. The squad resolver later picks the
matching `ea_id`. `INSERT OR IGNORE` on PK `ea_id` = idempotent re-load.

Key design points (full column list mirrors the CSV, renamed snake_case):

- **PK** `ea_id` (EA's `ID`).
- **Identity/meta:** `name`, `name_norm` (`lower(strip_accents)`), `gender`
  (filtered M), `ovr`, `position`, `alt_positions` (raw list string),
  `position_class` (derived), `nation_name`, `nation_code` (FIFA-3 via map),
  `league`, `club`, `age`, `preferred_foot`, `weak_foot`, `skill_moves`,
  `height_cm`, `weight_kg`, `source_url`, `card_url`, `ingested_at`.
- **6 family scores** — prefixed `ea_` to dodge the collision with the
  same-named sub-attribute: `ea_pace, ea_shooting, ea_passing, ea_dribbling,
  ea_defending, ea_physical`. (Only `Dribbling` actually collides family-vs-sub,
  but prefix all 6 for consistency.)
- **~29 sub-attributes** (snake_case as-is): `acceleration, sprint_speed,
  positioning, finishing, shot_power, long_shots, volleys, penalties, vision,
  crossing, free_kick_accuracy, short_passing, long_passing, curve, dribbling,
  agility, balance, reactions, ball_control, composure, interceptions,
  heading_accuracy, def_awareness, standing_tackle, sliding_tackle, jumping,
  stamina, strength, aggression`.
- **5 GK attrs** (nullable, GK-only): `gk_diving, gk_handling, gk_kicking,
  gk_positioning, gk_reflexes`.
- **`play_style_raw`** VARCHAR — keep the raw list verbatim (provenance);
  normalized form goes to the child table below.

### Child table — `ea_fc26_playstyle` (normalized for chessboard joins)

```sql
CREATE TABLE IF NOT EXISTS ea_fc26_playstyle (
  ea_id      INTEGER NOT NULL,    -- -> ea_fc26_player.ea_id (app-enforced)
  playstyle  VARCHAR NOT NULL,    -- base name, '+' stripped, e.g. 'Finesse Shot'
  tier       VARCHAR NOT NULL,    -- 'base' | 'plus'  (no '++' observed)
  PRIMARY KEY (ea_id, playstyle)
);
```

Parse: `'Finesse Shot+'` → `(ea_id, 'Finesse Shot', 'plus')`. The chessboard
player-modifier layer (pipeline stage 2c) joins this table to turn a player's
PlayStyles into `(zone, attribute) → modifier` boosts.

### Linking EA in — EA is the PRIOR, squad row is the hub

EA attaches to `wc2026_squad` via the new `ea_id` column (added above):
resolver = **`name_norm` + `nation_code`** primary; **club-alias + `age` vs
Wikipedia age** as tiebreakers (141 dup names mean name alone is unsafe).
So each squad row can carry both `our_player_id` (empirical refinement) and
`ea_id` (the ~100% attribute baseline) — the two coverage layers from
`analysis_pipeline_design.md`.

### Deferred within (b) — the EA-vs-empirical **blend formula**

The modeling core: how subjective EA attributes combine with empirical
match-derived metrics (prior mean + coverage-weighted update). **Its own next
decision** — not buried here. Feeds item (f) attribute synthesis + item (c)
coverage weight. Settle the exact shrinkage form there.

### Residual (loader dry-run, not design-blocking)
- Confirm outfield sub-attrs are non-null for all M rows (only GK cols checked).
- Confirm every `Height`/`Weight` matches the `Ncm/ Nkg` pattern (NaN handling).
- EA→`players` *direct* link (beyond via squad) deferred — only needed if we
  later want an EA prior for non-squad players (opponents' club form etc.).
