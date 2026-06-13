# Chessboard Item 7 — Zone-Battle Attribute Relevance + Resolution

> Designed S34 with the maintainer. The contest layer that turns the item-6 team
> boards + `player_adjusted_attributes_wide` + EA PlayStyles into per-zone control
> / threat. Feeds item 8 (aggregation → xScoreline). Build **one zone at a time.**

## Framework (applies to every zone)

**Geometry — 9 zones, authored once, mirrored.** 3 lane-types (LW≡RW, LHS≡RHS, C)
× 3 goal-relative band-levels (`B1↔B6, B2↔B5, B3↔B4`). The other three quarters of
the pitch are pure symmetric operations on these 9.

**4 profiles per zone:** Attack, Defense, Buildup, Pressure. The contest **pairing
is set by which goal the zone is near**:
- zone in possessor's **attacking half** → **Attack (poss) vs Defense (def)** — the chance contest;
- zone in possessor's **own half** → **Buildup (poss) vs Pressure (opp)** — the play-out contest.
- (Middle third pairing — TBD when we reach those zones.)

**Class-clean attributes (S27 buckets).** Each of the 29 attributes lives in exactly
one bucket — ATTACK, POSSESSION, DEFENSE, SKILLS, IQ, PHYSICAL. Duels pair the
attributes that *actually oppose each other* on the pitch (across buckets is fine —
nimble escape vs strong/aggressive dispossess), but **each attribute is used once
per contest** → no double-count. Within a bucket we use only the sub-attributes that
matter in that zone (the box ignores long_passing; build-up ignores finishing).

**Two-stage sequential resolution.** A battle is a sequence of opposed micro-duels in
two stages:

```
each duel D:   p_D = BT(att_score, def_score) = att_score / (att_score + def_score)
   att_score = Σ_players occ(p, zone, phase) · Σ_attr( w_attr · adj_attr(p) · family_mult(p, attr) )
   (def_score likewise over the defender's attrs in that duel)
stage score:   approach = Σ w_D·p_D over approach duels   (WEIGHTED, not mean)
               main     = Σ w_D·p_D over main duels
zone threat:   P(attacker prevails) = main · (g + (1 − g)·approach)
```

- `phase` selects the item-6 board: in-possession profiles (Attack, Buildup) read the
  **attack board**, out-of-possession (Defense, Pressure) read the **defence board**.
- **`g` = `approach_gate` ∈ [0,1], default 0** → pure multiplicative `approach·main`
  ("must get free AND finish"). `g>0` lets a world-class finisher threaten a bit even
  when marked out of it (maintainer liked this; banked as a tunable, off by default).
- **Stages are weighted**, not averaged (a box main weights the finish duel above the
  aerial duel unless supply is a cross).
- **BT** = Bradley–Terry win-probability; absolute rating scale largely cancels.

**PlayStyle modulation (item-5 families land here).** A family multiplies **only the
attributes in the duels it touches**, modestly: **base ×1.05 / plus ×1.10**. It tilts
a duel without dwarfing the underlying rating.

## Worked zone — Central · L1 (goal-adjacent central: B6 box / B1 box)

### Context A — Attack vs Defense (B6 box)
*Approach (get free + into position):*
| duel | attacker | defender | stage w |
|---|---|---|---|
| D1 movement | positioning 0.6 + reactions 0.4 | def_awareness 0.6 + reactions 0.4 | 0.55 |
| D2 shake-off | agility 0.5 + balance 0.5 | strength 0.5 + aggression 0.5 | 0.45 |

*Main (decisive act):*
| duel | attacker | defender | stage w |
|---|---|---|---|
| D3 finish/block | finishing 0.6 + composure 0.4 | standing_tackle 0.6 + def_awareness 0.4 | 0.70 |
| D4 aerial | heading_accuracy 1.0 | jumping 1.0 | 0.30 |

*Secondary (small additive, ~0.15):* att `volleys, shot_power, dribbling`; def `sliding_tackle, interceptions`.
*PlayStyle:* att Finishing↑finishing/composure (D3), Precision Header↑heading (D4), Dribbling/Movement↑agility/balance (D2); def Aerial Fortress↑jumping (D4), Block/Anticipate↑tackle/awareness (D3), Bruiser/Enforcer↑strength/aggression (D2).

### Context B — Buildup vs Pressure (B1 box)
*Approach (receive & survive the press):*
| duel | builder | presser | stage w |
|---|---|---|---|
| D1 calm-vs-closing | composure 1.0 | sprint_speed 0.5 + acceleration 0.5 | 0.50 |
| D2 lane/space | positioning 1.0 | interceptions 1.0 | 0.50 |

*Main (execute the out-ball):*
| duel | builder | presser | stage w |
|---|---|---|---|
| D3 play-out | short_passing 0.6 + long_passing 0.4 | interceptions 0.5 + standing_tackle 0.5 | 1.00 |

*Secondary:* build `ball_control, dribbling, vision`; press `stamina, aggression, def_awareness`.
*PlayStyle:* build Passing↑short/long pass + composure (Tiki Taka/Incisive/First Touch); press Press Proven↑pace/aggression, Anticipate/Intercept↑interceptions.

## Deferred / to-do

- The other 8 zones (each its own discussion, this is the template).
- Middle-third (L3) contest pairing — build-up vs attack ambiguity at halfway.
- **GK track** — build-up distribution (Central-L1 Buildup really starts with the GK);
  fold in when the GK model exists.
- Set-piece attrs (penalties, free_kick_accuracy) — parked overlay.
- Numeric weights + `approach_gate` g + family-multiplier sizes = **priors to calibrate
  vs StatsBomb**, not asserted truth.
