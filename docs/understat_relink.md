# Understat empirical relink (S45) — design

> Surfaced by the V3 ratings-audit page: Mbappé (and ~others) show `att_min=0`
> i.e. **no Understat attack/possession data**, so their attacking ratings run on
> the pure EA prior. Root cause is a name-linkage gap, not coverage.

## Finding (observed, not inferred)

- Understat **has** Mbappé: **5,561 min / 65 games**, stored as
  `Kylian Mbappe-Lottin` under Understat `player_id=3423`. Squad/FBref side is
  `Kylian Mbappe` under `our_player_id=50000477`.
- `players` (7,537 rows; cols `player_id, player_name, player_dob`) is a **union of
  two id spaces** — FBref (`50000xxx`, has dob) and Understat (small ids, dob
  null). The same person has separate rows with possibly different names.
- The blend engine (`_probe_adjusted_ratings.build`) pulls **FBref by
  `our_player_id`** but **Understat by hardened name**
  (`re.sub('[^a-z0-9]','', lower(strip_accents(name)))`). Name variants break the
  Understat path only:
  - suffix/middle: `mbappe` vs `mbappe-lottin`, `amad diallo` vs `amad diallo
    traoré`, `pape gueye` vs `pape alassane gueye`, `jonathan david` vs `jonathan
    christian david`;
  - word order: `hwang hee-chan` vs `hee-chan hwang`, `lee jae-sung` vs
    `jae-sung lee`;
  - non-Latin char: `Yıldız` → `strip_accents` drops the dotless ı → mangled.

## Scope (measured)

- 1,102 outfield players; 634 (58%) have `att_min=0`. **Most are legitimate** —
  Understat covers only the big-5 domestic leagues (EPL/La Liga/Ligue 1/
  Bundesliga/Serie A, 24-25 & 25-26); Saudi/MLS/Portugal/Greece/Turkey players
  correctly have none.
- A token-subset probe found **42** `att_min=0` players who *do* appear in
  Understat under a variant name. BUT that heuristic is **unsound alone**: mononym
  Understat entries collide — `danilo` (one row) matched both `danilo luiz` and
  `danilo santos`; `kevin` matched three; `pedro`/`fabian`/`rayan`/`nicolas`/
  `ederson` similarly. → must guard.

## Decision — guarded override pass (mirrors S44 EA relink)

Candidate generation, then **guard by club corroboration** (Understat
`player_match_stats.team` vs `wc2026_squad.club`) + token-subset name, write a
review CSV + proposed JSON; curate by hand (drop uncorroborated mononyms); persist
a verified `data/config/understat_id_overrides.json`
(`{squad_row_id: understat_player_id}`); consume + re-derive. Also fix the
`strip_accents` gap for the dotless-ı class.

### Where the fix lives — two options (pick one)

**Option 1 — engine-consumed override (recommended, smaller).** Build the override
JSON; in `_probe_adjusted_ratings.build`, after the name-based Understat match, for
overridden squad rows pull `player_match_stats` by the override `player_id`
instead. No DDL. Auditable, surgical, S44-style. Then re-derive
(`derive_adjusted_attributes --apply`) + rebuild downstream.

**Option 2 — resolve `understat_player_id` properly (cleaner, heavier).** Extend
`resolve_squad_links.py` to resolve a second empirical id with token+club guard,
persist a new `wc2026_squad.understat_player_id` column (DDL), and switch the
engine's Understat aggregation to that id. Symmetric with FBref, fully persisted,
but a wider blast radius (DDL + resolver + engine + re-derive).

### Build sequence (either option)
1. Candidate probe → review CSV + proposed overrides (guarded by club + token).
2. Human curation → `understat_id_overrides.json` (verified only).
3. Wire consumption (Option 1: engine; Option 2: resolver + column).
4. Re-derive adjusted attributes → rebuild eligibility/coverage/dashboard DB.
5. Verify: Mbappé `att_min` > 0, Attack blend now uses empirical; controls held
   (mononym non-matches stay dark); spot-check the audit page.
