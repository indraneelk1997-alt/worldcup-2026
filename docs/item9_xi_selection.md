# Item 9 — Position-aware XI selection (S42)

> Design doc. Written before code (rule 2). Captures the decisions locked in
> the S42 design conversation. Implementation target: `src/load/v2_ingest/
> zone_aggregate.py` (selection) + a new derived table built in `src/load/`.

## 1. Problem

`autopick_xi` reads each formation slot's granular `position_code` (`RB`,
`RCB`, `LB`, `LW`, `ST`, `DM`…) but collapses it through `SLOT_GROUP` to a
coarse group (`DEF`/`MID`/`FWD`) and then greedily fills by group only. The
slot's role and side are discarded, so:

- Harry Kane (a striker) is placed at `LW`.
- Marcus Rashford ends up at `ST` ahead of his real wide role.
- Cucurella (a left-back) lands at `RCB` for Spain.

The XI is the foundation of the whole sim — a wrong XI makes the formation,
the occupancy boards, the zone battles and the scoreline all wrong. Fixing
selection is the S42 headline; per-team formations, substitutes and the
player-stats panel sit on top of it.

## 2. Core idea (maintainer rule)

Replace "best available player in this group" with **empirical, position-aware
eligibility**:

> For each player, compute how his playing time is distributed across
> positions from the data we actually have. A player is **eligible** for a
> position only if he has played there in **> 20 % of his (minutes-weighted)
> appearances**. His **modal** position (highest share) is his primary.

Then assign players to slots respecting eligibility, side and quality.

## 3. Decisions locked (S42)

1. **Use all three empirical sources up front** — Understat + FBref (club) and
   StatsBomb (international tournaments). Rationale (maintainer): players show
   specialised roles at club level *and* a distinct national-team role in
   tournaments; both are relevant to a WC sim. Not phased.
2. **Threshold on minutes, not appearances.** A short cameo at a position must
   not count as a full appearance there. Unit = minutes share.
3. **Minimum-minutes floor ≈ 270 min** (≈ 3 full matches) of total empirical
   minutes before the distribution is trusted. Below the floor → fall back to
   EA `position` + `alt_positions`.
4. **RCB/LCB and wide-slot side split via `preferred_foot`** as the v1 flank
   mechanic, refined by StatsBomb's L/R lean where StatsBomb covers the player.

## 4. Position data inventory (observed, not inferred)

| Source | Table | Position field | Granularity | Coverage |
|---|---|---|---|---|
| Understat | `player_match_all` (`source='understat'`) / `player_match_stats` | `position` / `effective_position` (resolves `'Sub'`) | side-aware: `DC, DR, DL, DMC, MC, MR, ML, AMC, AMR, AML, FW` — **no L/R centre-back** | top-5 EU leagues; 3 465 players |
| FBref | `player_match_all` (`source='fbref'`) / `player_match_fbref` | `position` / `effective_position` | `CB, RB, LB, DM, CM, CAM, RM, LM, RW, LW, FW` — **no L/R centre-back** | FBref comps; 4 072 players |
| StatsBomb | `statsbomb_event.position` (+ `statsbomb_player_match` for minutes) | full names | **gold**: `Left/Right Center Back`, `Left/Right Wing`, `L/R Center Midfield`… — only source that splits CB and the wide channels fully | WC22, Euro24, Copa24, AFCON23 |

Already-derived helper: **`player_positions_v103`** = `(player_id, season,
team, position_code, minutes_in_role, n_matches, position_source)` in **our**
taxonomy — i.e. the Understat/FBref → canonical mapping already exists there.
It is keyed per season/team, so it must be **summed by `(player_id,
position_code)`** to get a player's overall distribution. It does **not**
include StatsBomb.

Worked check (Rashford, summing `player_positions_v103`): LAM 672 (56 %),
ST 284 (24 %), RAM 152 (13 %), CAM 90 (8 %); total 1 198 min. The 20 % rule →
**eligible LAM + ST; RAM, CAM drop; modal LAM.** Correct profile. The rule
behaves.

## 5. Two-stage position model

Pooling sources of different granularity directly fragments a player's centre-
back minutes across `CB` (Understat/FBref) and `LCB`/`RCB` (StatsBomb), which
would break the 20 % threshold. Resolve with two levels:

### 5a. Role eligibility (the 20 % threshold operates here)
Map every source code to a **role** taxonomy that all sources can express, so
minutes pool cleanly:

```
GK · CB · RB · LB · DM · CM · CAM · WIDE_R · WIDE_L · ST
```

- `WIDE_R` folds `RM / RAM / RW` (and StatsBomb Right Mid/Wing); `WIDE_L` the
  left mirror — so a left winger's `LW + LAM + LM` minutes pool into one role
  instead of fragmenting.
- `CB` folds StatsBomb `LCB/RCB/CB` + Understat `DC` + FBref `CB`.
- Pool **minutes across all three sources** into role shares. Eligible role =
  share > 20 %; modal role = max share. Below the 270-min floor → EA fallback
  (`position` → role at 1.0, each `alt_positions` entry → role at a discount).

### 5b. Slot matching + flank (fine codes resolved here)
Formation slots are finer than the role set. Map slot → eligible role(s),
then break the side within a role:

| Slot code | Primary role | Fallback roles (soft penalty) | Flank rule |
|---|---|---|---|
| `GK` | GK | — | — |
| `RCB` | CB | RB | StatsBomb R-CB lean if present, else right foot |
| `LCB` | CB | LB | StatsBomb L-CB lean if present, else left foot |
| `CB` | CB | — | — |
| `RB` | RB | DM, CB | right side |
| `RWB` | RB | WIDE_R, CB | right side (converted winger ok) |
| `LB` | LB | DM, CB | left side |
| `LWB` | LB | WIDE_L, CB | left side (converted winger ok) |
| `DM` | DM | CM | — |
| `RCM` / `CM` / `LCM` | CM | DM, CAM | side by foot for R/L variants |
| `CAM` | CAM | CM | — |
| `RM`/`RW`/`RAM` | WIDE_R | CAM, ST | right side |
| `LM`/`LW`/`LAM` | WIDE_L | CAM, ST | left side |
| `ST` / `FW` | ST | WIDE_*, CAM | — |

**Within-family folding is the deliberate inclusion mechanism.** `LW ≡ LAM ≡
LM` (→ `WIDE_L`) and `LB ≡ LWB` (→ `LB`), mirrored on the right, so a player who
only ever logged one of them is still eligible for the others' slots and his
minutes pool toward the 20 % test — no big player is missed, and we do not rely
on the manual swap to fix it. Folding is **within a family only, never across**:
a fullback is not auto-eligible at wing; if a player truly plays both, his
empirical minutes already say so.

Note: only StatsBomb resolves `RCB` vs `LCB` natively. For the (majority)
players StatsBomb doesn't cover, `preferred_foot` does the split — the standard
real-world convention (right-footed → RCB, left-footed → LCB).

## 6. Materialised table — `squad_position_eligibility`

Compute the shares **once at ingest**, not at dashboard runtime. The dashboard
trimmed DB dropped the StatsBomb raw tables (S40), so reading raw sources at
runtime is impossible there anyway. Output one small table, committed to
**both** the full and the trimmed DB:

```
squad_position_eligibility
  squad_row_id   INTEGER   -- FK -> wc2026_squad
  role           VARCHAR   -- GK/CB/RB/LB/DM/CM/CAM/WIDE_R/WIDE_L/ST
  minutes        INTEGER   -- pooled minutes in this role
  minutes_share  DOUBLE    -- role minutes / player total
  is_modal       BOOLEAN   -- highest-share role for the player
  eligible       BOOLEAN   -- minutes_share > 0.20
  source_mix     VARCHAR   -- e.g. 'understat,fbref,statsbomb' contributing
  cb_lean        VARCHAR   -- 'L'/'R'/NULL : StatsBomb centre-back side, if any
  basis          VARCHAR   -- 'empirical' or 'ea_fallback'
```

`autopick_xi` then reads only this tiny table + `wc2026_squad` (foot) +
`selection_scores` — fast, and identical for a clone-only friend.

### Build dependencies / risks to verify during build
- **StatsBomb minutes + position join:** `statsbomb_player_match` has minutes
  but no position; `statsbomb_event.position` has position on StatsBomb's own
  IDs. Need modal position per `(match_id, player_id)` from events, joined to
  the player's minutes, then linked to `wc2026_squad` by **normalised name**
  (the project's existing name-norm path). Verify the match rate before trust.
- **Source-minute weighting:** v1 pools raw minutes (club volume will dominate
  over tournament minutes). Flagged as a tunable — a later option is to weight
  international minutes up, since the sim is national teams. Not in v1.
- **`player_positions_v103` freshness:** confirm whether it already includes
  FBref or is Understat-only; if stale, recompute Understat+FBref shares from
  `player_match_all` (which carries `position`, `minutes`, `source`) using the
  same source→canonical map, and keep v103 as a cross-check.

## 7. Assignment algorithm

Greedy slot-filling double-binds players eligible for several slots (the first
slot grabs a star, a worse fit fills the second). Use a **global optimal
assignment** instead:

- Build an 11×N **fit matrix**: `fit(slot, player) = selection_score(player) ×
  position_fit(slot, player)`, where `position_fit` = `1.0` modal-role match,
  `0.7` other eligible role, `~0.15` soft fallback (ineligible but allowed so a
  thin squad still fields 11), × `0.85` on a flank/foot mismatch for a
  side-specific slot.
- Solve with `scipy.optimize.linear_sum_assignment` (scipy already in `.venv`,
  no new dep) maximising total fit.

This is the right tool for "assign N players to N slots optimally" and removes
the greedy ordering artefact.

## 8. Build plan (one step at a time)
1. **Source→canonical mapping** module + unit-check the vocabularies (StatsBomb
   names, Understat/FBref codes) against the `positions` table. *(observe)*
2. **StatsBomb per-player role-minutes** derive (events→modal per match→join
   minutes→name-link to squad); report match rate. *(verify before trust)*
3. **Build `squad_position_eligibility`** (pool 3 sources → role shares → 20 %
   + 270-min floor + EA fallback). Append-only loader, no DDL on existing
   tables (rule 9). Commit to both DBs via the `make_dashboard_db` path.
4. **Rewrite `autopick_xi`** to slot 5b + Hungarian assignment off the new
   table. Keep the old signature/return contract for the dashboard.
5. **Verify across nations** — ENG (Kane→ST, Rashford→WIDE_L, Saka→WIDE_R),
   ESP (Cucurella→LB not RCB), and a thin/limited-coverage squad to exercise
   the EA fallback. Compare XIs before/after.

## 9. Tunable knobs (defaults; revisit later)
- 20 % eligibility threshold; 270-min floor.
- `position_fit` weights (1.0 / 0.7 / 0.15) and flank-mismatch 0.85.
- `selection_scores` quality/caps blend (existing 0.6/0.4).
- Source-minute weighting (v1 = raw pool).

## 10. Downstream (later tasks, not this doc)
- **Per-team formation** (task #2): eligibility makes formation choice
  meaningful (pick the shape the squad actually fits).
- **Substitutes** (task #3): the non-selected eligible pool per role *is* the
  bench, ranked by `selection_score` — nearly free once §6/§7 exist.
- **Player-stats panel** (task #4): dashboard surfacing on top of a correct XI.
```