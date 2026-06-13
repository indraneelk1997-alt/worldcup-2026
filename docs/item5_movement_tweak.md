# Chessboard Item 5 — Player PlayStyle TWEAK (Movement leg)

> The TWEAK in `final = BASE(formation) ⊕ SHIFT(team playstyle) ⊕ TWEAK(player playstyle)`.
> Implements part of Decision 6 (chessboard_design.md). Designed S33; builds on
> item 4 (`kernel_transforms.py`) + formation assembly (`formation_assembly.py`).

## Scope — item 5 is split (decided S33)

Item-5 part (a) = the tag→family map (`data/config/playstyle_families.json`, 36
tags → 5 families + GK/set-piece carve-outs), validated against the live EA data
by `validate_playstyle_families.py` (PASS, 36/36).

Item-5 part (b) — the effects — splits by *kind* of effect:

- **Movement** family (Rapid, Quick Step, Relentless, Press Proven) = **kernel
  tweak** → reshapes occupancy → **built now** (this doc), plugs into assembly.
- **Finishing / Passing / Dribbling / Defending** = **attribute emphasis** → they
  do NOT move the kernel; they weight *which* of the 29 attributes a player
  threatens/defends with. D6 says these compound with the item-7 zone-attribute
  relevance matrix → **deferred to item 7**, where they have something to modulate.

So only Movement touches the board; the rest waits for item 7.

## Movement effects (per-player, modest, ON TOP of the team SHIFT)

| tag | effect | base | plus | phase |
|---|---|---|---|---|
| Rapid | forward band **shift** | +0.30 | +0.45 | attack |
| Quick Step | forward band **shift** | +0.20 | +0.30 | attack |
| Press Proven | forward band shift | +0.30 | +0.45 | defence |
| Relentless | **spread** (dilation) | +0.15 | +0.25 | both |
| Relentless | **availability** boost | +0.10 | +0.15 | both |

- **Rapid / Quick Step** — a forward **translate** of the *attack* kernel, NOT a
  forward extension/tail. These players stay as advanced as possible to exploit
  space ahead, so the whole attacking shape moves up; it does not just grow a
  forward tail. Rapid > Quick Step (top speed vs burst). Magnitudes in band units.
- **Press Proven** — forward translate of the *defence* kernel, additive on top of
  the team `press_push`. A personal high-press.
- **Relentless** — the box-to-box roamer does TWO things: (1) **dilation** (the one
  new operation) — scale each cell's distance from the kernel's own (per-phase)
  **base centroid** by `(1 + spread)`, applied *before* the translates (footprint
  grows, average position unchanged); and (2) an **availability boost** — the
  player's presence budget rises above 1.0 (base 1.10 / plus 1.15) so his kernel
  sums to >1, making him **more available** across zones (he tilts marginally more
  zone battles — "he's everywhere"). This is a deliberate, documented departure
  from the D4 budget=1.0 default, and applies ONLY to Relentless players. The
  team is intentionally NOT renormalised back to 10.0 — the extra presence is the
  point.
- A player carrying several Movement tags → effects **add**.

`tier` (base/plus from `ea_fc26_playstyle`) sets magnitude. Effects kept modest —
this is a positional/qualitative layer, and (per D6) must never re-inflate the
S29 adjusted attribute values (it doesn't — it only moves occupancy).

## Integration

1. **Assembly gains an optional XI.** `assemble(..., xi={slot_no: ea_id})`. For
   each slot we pull that player's Movement tags (filtered through the family
   map) + tiers and compute the per-slot tweak. **No XI → TWEAK neutral**
   (formation-only behaviour stays the default). This realises the rest of
   decision B: formation + *players* + playstyles → transform.
2. **One resample.** `transform_kernel` is extended to accept per-phase extra
   band-shifts + a spread factor, so SHIFT and TWEAK fold into a **single** splat
   (splatting twice would blur the kernel twice).
3. **Spread is relative to the base kernel's per-phase centroid**, applied before
   all translates.

## Config

Extend `data/config/kernel_transforms.json` with a `movement_tweak` block holding
the base/plus magnitudes above (env-overridable, same posture as the item-4 gains;
priors to calibrate vs StatsBomb, not asserted truth).

## Banked for later (NOT built now)

- **Danger-zone nudge (→ item 8, zone battle):** Rapid/Quick Step also give "half a
  step extra" to create a threat specifically in dangerous zones. That is a
  battle-layer threat effect, not occupancy — handle in item-8 zone-battle logic.
- **Quick Step lateral separation (v2):** Quick Step also helps mids/wingers move
  laterally to escape a marker. Possible future lateral tweak component; use
  unclear, noted.
- **Pace ↔ pressing (ignored v1):** pace players sometimes press less to stay
  forward. Deliberately not modelled now.
