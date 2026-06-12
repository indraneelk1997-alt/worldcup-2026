# D2 — StatsBomb-team → 2026-nation map

> Bridges the empirical playstyle leg (`team_playstyle_empirical`, S31) to the
> 48 WC2026 nations, so the D2 prior+blend (next) can attach each nation's
> empirical rows. Designed S32. Companion config:
> `data/config/statsbomb_team_aliases.json`.

## Resolution rule

`team_playstyle_empirical` stores the SB team **name string** (e.g. `Spain`,
`Côte d'Ivoire`). The 48 WC2026 nations live in `data/config/nation_codes.json`
keyed by their Wikipedia/WC2026 English name → FIFA-3 code. Resolution is a
two-hop, exact-match only (no fuzzy — rule 3, and we have the full string list):

```python
nation_key = aliases.get(sb_team, sb_team)      # statsbomb_team_aliases.json
fifa3      = nation_codes.get(nation_key)        # nation_codes.json; None => not a 2026 qualifier
```

`nation_codes.json` stays the **single source of truth** for codes; the alias
file is a thin overlay for the only 3 SB strings that don't match a nation key.
No new table, no schema change, no touch to `team_playstyle_empirical`
(persistence decision **(b)**; promote to a materialised xref **(c)** when the
blend deriver lands and can emit `nation_fifa3` as a column on its own output).

## The 3 aliases (the only non-exact matches)

| StatsBomb string | nation_codes.json key | FIFA-3 |
|---|---|---|
| `Cape Verde Islands` | Cape Verde | CPV |
| `Congo DR` | DR Congo | COD |
| `Côte d'Ivoire` | Ivory Coast | CIV |

All other 68 SB strings (incl. `South Korea`, `United States`, `Saudi Arabia`,
`Turkey`) match a `nation_codes.json` key exactly.

## Reconciliation (verified vs live 96-row dump, S32)

96 team-tournament rows = **71 distinct SB teams** across WC22 (43,106),
Euro24 (55,282), Copa24 (223,282), AFCON23 (1267,107). Against the 48 nations:

- **39 SB teams ARE 2026 qualifiers** → resolve to a FIFA-3 code (some appear in
  two tournaments, e.g. Spain WC22+Euro24, Morocco WC22+AFCON23 — kept at the
  `(team, tournament)` grain; recency weighting is the blend's job, not the map's).
- **32 SB teams are NOT 2026 qualifiers** → resolve to `None`, not joined into the
  2026 model. (Albania, Angola, Bolivia, Burkina Faso, Cameroon, Chile, Costa
  Rica, Denmark, Equatorial Guinea, Gambia, Georgia, Guinea, Guinea-Bissau,
  Hungary, Italy, Jamaica, Mali, Mauritania, Mozambique, Namibia, Nigeria, Peru,
  Poland, Romania, Serbia, Slovakia, Slovenia, Tanzania, Ukraine, Venezuela,
  Wales, Zambia.)
- **9 of the 48 nations have NO SB row** → **pure prior** (no empirical leg):
  Bosnia and Herzegovina, Curaçao, Haiti, Iraq, Jordan, New Zealand, Norway,
  Sweden, Uzbekistan.

Checks: 39 + 32 = 71 SB teams ✓ ; 39 + 9 = 48 nations ✓.

## Decisions

- **Keep all 96 rows; do NOT re-normalise the percentile axes.** The axes are
  percentile-ranked across the full 96-row pool. The 32 non-qualifiers are
  legitimate international sides that make the percentile scale more
  representative of "what international football looks like," so they stay in the
  pool even though they aren't joined into the 2026 model. A 2026-only re-norm
  (39 rows) would shrink and bias the scale — **banked** as a v2 option only if
  validation demands it.

## Banked ideas (v2)

- **Non-qualifier SB sides as proxies for dark nations.** The 32 non-qualifiers
  carry real empirical playstyle vectors and could seed/anchor the hand prior
  for the 9 (or other) data-less sides by stylistic/regional analogy — e.g.
  Norway/Sweden ← Nordic profile from Denmark; Bosnia ← Serbia/Croatia; Curaçao/
  Haiti ← CONCACAF profile from Jamaica/Panama. **Honest limit:** the AFC/Gulf
  dark set (Iraq, Jordan, Uzbekistan) has no good SB proxy — the structurally
  dark set flagged in S26 (their tournament, AFC Asian Cup 2023, isn't in
  StatsBomb open data). So proxying helps the Euro/CONCACAF dark sides but the
  Gulf/AFC sides remain genuine hand-prior. Document only; not built.
- **(c) Materialised xref** `statsbomb_nation_map(sb_team, nation_fifa3, …)` —
  promote from config-resolve to a persisted, auditable table when the blend
  deriver is written.
