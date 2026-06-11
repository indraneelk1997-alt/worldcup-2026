# Analysis pipeline design — attributes → zonal battles → xScoreline → sim

**Status:** vision / approach, agreed S22-close (2026-06-11). Forward-
looking design for the S23+ dashboard + modelling track. No code yet.
This is the "what and why"; per-stage build plans land in
`docs/dashboard_design.md` + `docs/data_sourcing.md` as we go.

## The pipeline (four stages)

1. **Player Att/Mid/Def attributes** — synthesize attacking / holding /
   defensive / creative attributes per player from whatever match-level
   stats we can get, per-90, position-relative.
2. **Zonal pitch logic ("the chessboard")** — a hand-built tactical
   model of pitch zones + formations + playstyles that decides
   *zone-battle* outcomes between opposing players.
3. **Team xScoreline correlations** — aggregate zone-battle outputs to
   team level; learn which features drive scoreline vs expected
   scoreline (feature importance).
4. **Match simulation** — simulate from the zone-battle / xScoreline
   model.

The **visual dashboard (Streamlit)** is the base layer: it feeds stage 1
(derive + eyeball attributes), and visually defines/validates stage 2
(zones, playstyles, battles).

## Data strategy — coverage as a *feature*, not a blocker

We do **not** chase club-league data for every WC squad player. Instead:

- **Prioritise international football** (FBref via the Option-C
  machinery already built): WC Qualifiers ×6 confederations, friendlies,
  Nations League, continental tournaments (AFCON, Asian Cup, Gold Cup,
  Copa, Euro). This gives *some* data on *most* national-team players —
  shape/counting stats (no xG post-Opta), which is enough for attribute
  derivation.
- **+ StatsBomb Open** (free, event + 360 spatial) for WC22 / Euro24 /
  Copa24 / AFCON23 — the deep spatial source (see "validation" below).
- **+ existing** top-5 domestic (Understat, xG) and UCL (FBref).
- **+ EA Sports FC 26 player database** (free, via Kaggle CSV — NOT
  SoFIFA, which is Cloudflare-blocked per Claude.md). This is the
  **coverage solver**: EA rates ~18k+ players globally incl. minor
  leagues, so nearly every WC squad player has a ready-made attribute
  set (6 main + ~35 detailed attributes: Pace, Dribbling, Defending,
  Tackling, Passing, Shooting, Physical…, + position, nation, age, club)
  **and EA "PlayStyles"** tags (Quick Step, Finesse Shot, etc.). It is a
  curated/subjective expert prior (EA scout network, Opta-informed), not
  match-derived — so use it as a **prior / gap-filler**, validated
  against empirical stats where both exist, never letting it override
  real data. Join to our `players` by (name, nation, dob, club) — dob
  now available helps the match.
- **Optional Tier-1 paid API** (Sportmonks/api-football) only to fill
  non-top-5 club coverage + xG, after verifying per-comp xG coverage.

**Per-player data-coverage metric.** Each player gets a coverage score
(e.g. Haaland ~100%, an obscure squad player ~0%) based on
matches/minutes of data we hold (international + club, recency-weighted).
Two uses:
- **Dashboard feature** — show how much we actually know about a player.
- **Predictor confidence weight** — low coverage → shrink the player's
  match-derived attributes toward a prior. Crucially, with EA FC the
  prior is **informative** (the player's EA attribute set) rather than a
  bare position-average, so a thin-data player still has a credible
  profile. Plugs directly into the empirical-Bayes shrinkage already in
  the model (`player_season_stats.shrunk_form_eb` etc.). So coverage is
  **two-layer**: EA FC gives ~100% *attribute* coverage for nearly all
  squad players (the baseline), and empirical match data *refines* it
  where we have it. Well-covered, deep-run teams predict sharply; thin
  teams fall back to the EA-informed prior gracefully.

## Stage 2 — the chessboard tactical model

A parameterised tactical prior, NOT a black box. Three components:

### a. Pitch zone grid
Grounded in **Expected Threat (xT)** — Karun Singh's value surface that
divides the pitch into a grid (commonly 16×12 = 192 zones), each zone
carrying move/shoot/transition/goal probabilities, solved iteratively.
xT gives us a *principled value per zone* to weight battles by (a duel
won in a high-xT zone matters more). For interpretability we overlay
**Juego de Posición** lanes — central / two half-spaces / two wings ×
thirds — since half-spaces are the high-danger channels.

### b. Formation → zone occupancy
Reuse existing infra: `formations` + `formation_slots`
(formation → slot → `position_code`) already exist. Extend with, per
position slot, a **primary/secondary zone occupancy map for attack and
defence phases**. This is the "pieces on the chessboard."

### c. Playstyle archetypes
Low block, high line / offside trap, counter-attacking, tiki-taka /
positional, gegenpress / high press, direct, possession-control, etc.
Grounded in the playstyle-classification literature (clustering studies
converge on ~4 macro-styles: direct/British, Spanish ground-direct,
controlled-possession-counter, positional/tiki-taka). Each playstyle is
a **modifier set** on the base formation zone map + tempo/directness.
Note the two layers: **team** playstyle (above) sets the zone map;
**player** EA "PlayStyles" tags + attributes (Pace/Dribbling/Defending…)
feed the per-player zone-battle modifiers — e.g. a "Quick Step" +
high-pace LW vs a low-pace/low-tackle RB is exactly the kind of
attribute mismatch that boosts that zone's xThreat.

### Zone-battle mechanics (the core idea — S22-close clarification)

Each zone is a **matchup** between the opposing players/positions that
occupy it (per formation + playstyle). **Playstyle and player attributes
modulate the influence of a zone and of specific attributes within it**,
which decides the zone-battle outcome → contributes xThreat / xA for
that zone → aggregates to team xScoreline.

> Worked example: a pacy, good-dribbling **LW** vs a slow **RB** with
> poor tackling stats. The relevant playstyle (e.g. wing-focused /
> counter) **boosts the xThreat/xA probability of that zone**, making it
> a crucial strength for the LW's team. We build a library of such
> `(zone, attribute, playstyle) → modifier` rules: a playstyle
> strengthens or weakens specific attributes' influence in specific
> zones, and the resolved per-zone matchups feed the scoreline model.

So the model is: **attributes × zone-occupancy × playstyle-modifiers →
per-zone expected output → team xScoreline → simulation.**

### Validation discipline (the guard on a hand-built prior)
A tactical prior risks encoding bias. The check: **validate the
formation→zone occupancy priors against StatsBomb Open's real spatial
data** (actual touch / action locations in WC22/Euro24/Copa24/AFCON23)
before trusting them. StatsBomb Open is our *validation set*, not just
another data source — build prior → check against spatial truth →
calibrate.

## Stage 1 — attribute synthesis (feeds stage 2)

- Inputs: per-player counting stats (FBref Performance group —
  Gls/Ast/Sh/SoT/Tkl(W)/Int/Crs/Fls/Fld/Off…), plus Understat xG/xA
  where available, **plus the EA FC attribute set as an informative
  prior / gap-filler** for every player.
- Synthesize **Att / Mid / Def / creative** attributes via our own
  formulas (documented), per-90, **position-relative percentiles** (a
  CB's defensive baseline ≠ a striker's), **shrunk by coverage toward
  the EA-FC prior**. Open design question to settle in S23+: how exactly
  to blend subjective EA ratings with empirical match-derived metrics
  (e.g. EA as prior mean + empirical as the update, weighted by
  coverage) — don't let EA dominate where real data exists.
- Where only **team-level** stats exist, distribute to players via the
  chessboard zone-occupancy weights (stage 2 feeds back into stage 1
  attribution).

## What the dashboard surfaces (v1 targets)

- Player view: attribute radars, per-90 production, **coverage
  indicator**, position, age (dob now available).
- Team view: formation + **zone chessboard** occupancy, classified
  **playstyle**, attack/defence zone strengths.
- Zone-battle view: opposing zone matchups + resolved xThreat/xA.
- xG-haves vs shape-only sources clearly flagged throughout.

## References

- Expected Threat (xT) — Karun Singh:
  https://karun.in/blog/expected-threat.html ; possession-value overview:
  https://www.hudl.com/blog/possession-value-models-explained
- Playing-style classification (peer-reviewed):
  - Tactical Situations & Playing Styles as KPIs:
    https://pmc.ncbi.nlm.nih.gov/articles/PMC11130910/
  - Data-driven playing-style classification + match-outcome prediction
    (UCL): https://pmc.ncbi.nlm.nih.gov/articles/PMC12954490/
- Positional play / half-spaces (concepts):
  https://breakingthelines.com/tactical-analysis/what-is-juego-de-posicion/ ;
  https://learning.coachesvoice.com/cv/positional-play-football-tactics-explained-guardiola-cruyff-manchester-city/
- StatsBomb Open Data (spatial validation set):
  https://github.com/statsbomb/open-data
- EA Sports FC 26 player database (attributes + PlayStyles, free via
  Kaggle CSV — avoids the SoFIFA Cloudflare block):
  https://www.kaggle.com/datasets/talhademirezen/fc-26-player-stats ,
  https://www.kaggle.com/datasets/flynn28/eafc26-player-database ;
  official ratings reference: https://www.ea.com/en/games/ea-sports-fc/ratings
- Data-source pricing comparison: see chat S22-close / to land in
  `docs/data_sourcing.md`.
