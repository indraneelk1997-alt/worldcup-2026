# Resolver design — wc2026_squad ↔ EA prior / empirical / StatsBomb

**Status:** design, started S26 (2026-06-12). Design-first, one decision at a
time (no code yet). Companion to `docs/data_sourcing.md` (squad + EA as-built)
and `docs/analysis_pipeline_design.md` (coverage = a feature). Captures the
matching/confidence model that fills the link columns already on
`wc2026_squad`.

## Purpose

`wc2026_squad` (1247 rows) is the hub. The resolver fills its link columns by
matching each squad player to:
- **`ea_id`** → `ea_fc26_player` — the EA attribute **prior** (high value:
  the baseline attribute set for nearly every player).
- **`our_player_id`** → `players` — the **empirical** match-derived link
  (refines the prior where we have club/intl data).
- **(optional) StatsBomb** → a separate xref table (sidecar is on its own ID
  space; never a column on `players`). Low yield — see coverage below.

Each link records a `*_method` + `*_confidence` so the dashboard can show
*how* we know a player and the predictor can shrink accordingly. The resolver
is a **re-runnable UPDATE-by-`squad_row_id`** pass (idempotent; never touches
the roster rows themselves), per `data_sourcing.md`.

## Observed coverage (S26 probes — the numbers we're designing against)

squad = 1247. Exact `name_norm` (accent-folded, lowercased) both sides:

| Target | any candidate | ambiguous (>1) | strong-confirm | no match |
|---|---|---|---|---|
| EA (`ea_fc26_player`) | **850** | 9 | nation/age | 397 |
| Empirical (`players`) | **641** | some | 417 dob-confirmed | 606 |
| StatsBomb (strict name+nation) | 275 | — | nation-confirmed | — |

Coverage matrix (EA + empirical, exact): both=595, ea_only=255, emp_only=46,
**dark=351**. + StatsBomb (strict) lights 29 of the dark → **truly dark=322;
overall covered 925/1247 = 74.2%**.

Key S26 finding (banked): the 322 truly-dark is **largely genuine absence**,
concentrated in **AFC/Gulf football** (Jordan, Uzbekistan, Iraq, Qatar, Iran,
Saudi). Their tournament — **AFC Asian Cup 2023** — is not in StatsBomb open
data, so free sources structurally cannot cover them. Fuzzy matching does NOT
recover these (Jordan 0/26 = not in any of the 4 tournaments; Qatar 3/26 =
real roster turnover WC22→2026). → resolves the parked **paid gate**: only a
paid Asian-coverage feed fills the dark set; free path can't.

Separately, S24 probe: **150** of the 397 EA-unmatched squad players share a
surname with some EA player → likely name-FORM differences (word order, extra
given names, Mohammed/Mohamed), i.e. *recoverable same-person* matches, not
absence. This is the lever the fuzzy decision (D1) is about.

## Banked matching model (S23/S24 — don't relitigate, design HOW)

- **Candidate-generate by `name_norm`, then disambiguate by what each
  candidate carries** — NOT a fixed key ladder (our base is mostly
  dob-NULL / nation-NULL).
- EA: `name_norm` + **nation** primary (EA has nation), club-alias + age as
  tiebreakers (EA has 141 dup names → name alone unsafe).
- Empirical: `players` carries `player_dob` for the FBref subset only
  (~4070); Understat subset has neither dob nor nation → name + club-alias
  (via match tables) is the weak fallback. **Club is a tiebreaker only**
  (drifts hard: Dortmund/Borussia Dortmund…).
- StatsBomb: `name_norm` + nation (StatsBomb `team` = national team).

## Alias maps the resolver needs
- **EA nation_name → FIFA-3** (Holland→NED, Korea Republic→KOR…) on top of
  `nation_codes.json`.
- **StatsBomb team → FIFA-3** (Cape Verde Islands→CPV…) — small gap found S26.
- **Club alias** (soccerdata short ↔ Wikipedia/EA long) — tiebreaker only.

## Decision log

### D1 — Candidate generation: exact + guarded fuzzy — ✅ LOCKED (S26)

Two-stage candidate generation:
1. **Exact `name_norm`** (accent-folded, lowercased) — the primary pass.
2. **Guarded fuzzy** for still-unmatched squad rows: surname-anchored +
   ratio-over-threshold candidates, **promoted to a link only when nation
   agrees**. Age/dob *corroborates* when present (→ higher confidence,
   `fuzzy+nation+age`); when age/dob is missing, **nation-only is accepted**
   (`fuzzy+nation`, lower confidence). Recorded as a distinct method so the
   predictor can weight fuzzy links down.

Rationale: recovers the ~150 name-form EA-prior matches (≈38% of the EA gap)
that exact-only forfeits; the nation guard kills nearly all false positives.
Caveat (proven S26): fuzzy recovers **nothing** for the 322 truly-dark —
those are genuine absence, not misspelling. Payoff is entirely in
prior/empirical coverage for nations we already have.

**REVISED on dry-run evidence (S26).** The first dry-run showed the nation+age
guard is INSUFFICIENT: same-nation same-age names with near-identical
romanizations mis-merged — `mohamed alaa → mohamed salah` (EGY),
`kim jin gyu → kim min gyu`, `kim tae hyeon → kim dae hyeon` (KOR) — all
passed `fuzzy+nation+year`. No cutoff short of exact separates 1-edit Korean
names. Meanwhile the *good* fuzzy hits were all punctuation/spacing of the
SAME person (`son heung-min` == `son heung min`). So:
- **`name_norm` strengthened**: strip ALL non-alphanumerics (spaces, hyphens,
  dots, stray `ı`) on all three sources → safe variants become **exact**.
- **Generic fuzzy DROPPED from the default**; gated behind `--fuzzy` (off).
  "Better dark than wrong" (D3) over recovering a handful of nicknames at the
  cost of wrong-attribute injection.

### D2 — Scope: EA + empirical now; StatsBomb xref deferred — ✅ LOCKED (S26)

Build the **`ea_id`** (prior) and **`our_player_id`** (empirical) links this
session. **Defer the StatsBomb player xref.** Rationale:
- StatsBomb's designed role is the **spatial validation set**, and the 360
  frames are **anonymized** — they need no player link. So deferring the
  xref does NOT block the chessboard.
- Note: `statsbomb_event` DOES carry StatsBomb's `player_id` (1718 distinct)
  — per-player intl stats are fully available, just keyed by StatsBomb's own
  id. The deferred piece is only the cross-walk StatsBomb id → our ids,
  buildable anytime, needed only once attribute-synthesis consumes per-player
  intl stats. Low payoff now (29 otherwise-dark of 275 matched).

### D3 — Confidence model: discrete method-tier lookup — ✅ LOCKED (S26)

`link_method` encodes which signals corroborated; each maps to a documented
confidence band (numbers tunable, shape locked):

Corroborator = **birth year** (exact when from a real `dob`/`player_dob`;
±1 when derived from an integer age like EA's — absorbs FBref dob-drift for
free; full-date matching dropped as wasted effort, S26 maintainer call).

| method | confidence | applies to |
|---|---|---|
| `exact+nation+year` | 0.95 | EA / empirical (FBref) |
| `exact+year`        | 0.90 | empirical FBref (no nation on `players`) |
| `exact+nation`      | 0.85 | EA, no year |
| `exact+club`        | 0.60 | empirical Understat (club tiebreaker) |
| `exact`             | 0.55 | unique name, no other signal (accept-low) |
| `fuzzy+nation+year` | 0.65 | D1 fuzzy, corroborated |
| `fuzzy+nation`      | 0.50 | D1 fuzzy, nation-only |
| `none`              | NULL | unresolved / rejected |

**Policy: nation *mismatch* on an otherwise-good name match → reject (NULL),
not a low link.** A wrong link injects wrong attributes with false confidence
— worse than dark (which the position-average prior handles). Better dark
than wrong. Continuous-score model rejected (less auditable, granularity not
needed yet).

### D4 — Per-target disambiguation ladders — ✅ LOCKED (S26)

Corroborator = **birth year** (low-effort; collision-proof with name+nation).

**EA ladder** (squad → `ea_fc26_player`; EA always has nation + age→year):
1. exact `name_norm` → candidates
2. **1 cand** → nation agrees? +year agrees → `exact+nation+year`; year n/a →
   `exact+nation`; **nation mismatch → reject (`none`)**
3. **>1** (the 9) → filter nation → year → club-alias, until unique; else `none`
4. **0** → fuzzy (surname + ratio), require nation → `fuzzy+nation+year` /
   `fuzzy+nation`; else `none`

**Empirical ladder** (squad → `players`; FBref subset = `player_dob` + nation
via `player_match_fbref`; Understat subset = name + club only):
1. exact `name_norm` → candidates
2. **FBref cand** → birth-year agrees? → `exact+year` (or `exact+nation+year`
   if nation via `player_match_fbref` also agrees); year off → reject
3. **Understat cand** → club-alias agrees → `exact+club`; unique name, nothing
   to check → **`exact` (0.55) accept-low** (B: no nation to mismatch on;
   these are top-5 players — accept + flag)
4. **>1** → disambiguate by year (FBref) then club (Understat); else `none`
5. **0** → fuzzy only where nation exists (FBref subset); Understat fuzzy can't
   corroborate → `none`

Notes: `player_match_fbref.nation` is already FIFA-3 (no alias needed);
EA `nation_name` is full text (needs the alias map, D5). dob-drift is absorbed
by year-granularity.

### D5 — Alias maps: EA-nation only; skip clubs for v1 — ✅ LOCKED (S26)

- **EA `nation_name` → FIFA-3: BUILD**, observe-driven (dump EA distinct
  nation_names, map onto `nation_codes.json` + alias overlay, report
  unmapped). Nation is the EA ladder's primary corroborator.
- **Club alias map: SKIP for v1.** Only a tiebreaker, and birth-year+nation
  almost always resolves first. Fires only for >1 same-`name_norm` Understat
  candidates → let those fall to `none` (flagged), don't hand-curate hundreds
  of aliases. Revisit only if the dry-run shows it actually firing.

## Design status — ✅ COMPLETE (S26)

D1–D5 locked. Resolver = exact+guarded-fuzzy candidate gen (D1) → per-target
year+nation disambiguation ladders (D4) → discrete-tier confidence (D3),
filling `ea_id` + `our_player_id` on `wc2026_squad` (D2); StatsBomb xref +
club aliases deferred (D2/D5). Idempotent UPDATE-by-`squad_row_id`.

**Next:** observe EA distinct `nation_name`s → build the EA-nation alias map →
write `resolve_squad_links.py` (dry-run prints the method/confidence
distribution + unmatched/ambiguous before any UPDATE).
