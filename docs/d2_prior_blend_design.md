# D2 — prior leg + blend (team playstyle)

> Combines the empirical leg (`team_playstyle_empirical`, S31; bridged to nations
> by `docs/d2_nation_map.md`, S32) with a prior into one current-2026 5-axis
> playstyle vector per nation. Designed S32. Companion configs:
> `data/config/statsbomb_team_aliases.json`, `data/config/coach_continuity.json`.
> Axes: `[directness, width, line_height, press, possession]`, all on the
> percentile-normalised 0–1 scale of `team_playstyle_empirical`.

## The blend

```
axis_2026 = (1 − λ_team)·prior + λ_team·empirical_vec
```

`λ_team ∈ [0, λ_max]` is our confidence that a nation's empirical vector still
represents its 2026 style. High λ_team (recent, multi-tournament, same coach) →
empirical dominates. Low/zero λ_team (stale, thin, coach changed, or no data) →
the prior fills in.

## λ_team — one evidence currency, used twice

A nation has 1–2 empirical rows (one per tournament it appears in: Spain =
WC22+Euro24; Qatar = WC22 only). Each row gets an **evidence weight**:

```
e_r = recency(tournament) × volume(matches_r) × continuity(nation, tournament)
```

Then the *same* weights both combine the rows and set the trust:

```
empirical_vec = Σ_r e_r·vec_r / Σ_r e_r           # recency-weighted mean of the rows
λ_team        = λ_max · (1 − exp(−Σ_r e_r / τ))    # accumulated evidence → confidence
```

This is deliberately the **S27 coverage-λ noisy-OR shape** (saturating
evidence→confidence, `docs/coverage_prior_design.md`) and the **S28 confidence
CAP** (`λ_max`, `docs/blend_redesign.md`) reused — one consistent confidence
idiom across the project. One currency means a nation's stale-but-only data
(e.g. Morocco WC22 possession .11) and its recent data (Morocco AFCON23 .78)
auto-reconcile by weight rather than a bespoke rule.

### The three factors

- **recency** — discrete, two epochs only (no false-precision decay over two
  points). `2024 tournaments (Euro24/Copa24/AFCON23) = 1.0`; `WC22 = ρ` (one
  tunable, **locked 0.8** S32). AFCON23 is Jan 2024, grouped with 2024.
- **volume** — saturating `m_r / (m_r + m₀)` on matches played in the tournament
  (**locked `m₀ = 3`** S32): a finalist (7 matches) is a tighter estimate than a
  group-exit (3). Nudges confidence, never the axis value.
- **continuity** — `1.0` if the tournament manager still leads the side in 2026,
  else `coach_change_discount` (default **0.5**). From
  `data/config/coach_continuity.json` (gathered from Wikipedia). This is the
  factor that most directly de-weights stale WC22 vectors under new managers.

### Single λ_max (v1)

One global `λ_max` (**locked 0.9** S32), not per-axis. Unlike S27's mismatched
sources (xG vs counting-stat proxies, which warranted per-dimension CAPs), all 5
playstyle axes derive from the *same* StatsBomb event quality, so a single cap is
honest here. Per-axis caps **banked** for v2 if validation shows one axis
(e.g. line height / PPDA, the noisier two per S31) needs less trust.

### Tuning outcome (S32 sweep — `_probe_blend_sweep.py`)

Swept shrinkage baseline→minimal. Decision driver (maintainer): tournament
football is where sides express identity, not experiment, so let well-covered
sides move *off* the prior — plenty of sides sit near it anyway (thin data,
coach changes). **Locked "S2b": `ρ=0.8, m₀=3, λ_max=0.9, τ=0.4`.** Rationale:
`λ_max=0.9` lets identity through; the higher `τ=0.4` (vs the more aggressive
`τ=0.3`) keeps the evidence curve *separating* well-covered from thin — at S2b,
elites (Spain 0.81, Argentina/France 0.86, Portugal/Uruguay 0.80) hold while
thin/coach-changed sides (Qatar/Iran 0.35) stay humble, instead of a uniform
lift. Personality (mean `|blend−prior|`) ≈ doubles vs the old default, and the
well-covered gain more than single-row sides (0.125 vs 0.105). Mean λ over the 39
blended = 0.65. Rejected S3 (`λ_max=0.95, τ=0.25`): over-trusts thin stale data
(Qatar 0.56).

## The prior — confederation-mean shrinkage, not 48 hand vectors

The prior is **not** hand-authored per nation. For a data-rich side λ_team is
high and the prior barely matters, so a hand number there is labor with no
payoff; and an arbitrary hand vector is less defensible than a data-driven one.

**Prior = the confederation mean** of the empirical vectors we *do* have:

```
prior(nation) = mean( empirical_vec over qualifier sides in the same confederation )
```

So Norway shrinks toward the European empirical mean, Curaçao/Haiti toward
CONCACAF, etc. This is empirical-Bayes / James–Stein shrinkage toward the group
mean — reproducible, and it formalises the "non-qualifier sides as proxies"
idea banked in `docs/d2_nation_map.md` (the confederation mean is computed over
*all* SB sides in that confederation, qualifiers and non-qualifiers alike, since
both inform "what this region's football looks like").

**Global-mean fallback only where a confederation has no SB pool.** Observed S32:
every confederation except OFC has SB sides — crucially the **AFC pool has 9**
(Australia, Iran, Japan, Qatar, Saudi Arabia, South Korea + the qualified East-
Asian/Gulf WC22 sides), so the dark AFC trio (Iraq, Jordan, Uzbekistan) **do**
shrink toward an AFC mean, not a global one. The *only* nation with no
confederation-mate in the SB pool is **New Zealand** (sole OFC side) → global
mean (or a hand vector). Hand priors remain available as an **optional override**
anywhere the maintainer has strong knowledge and wants to overrule the
confederation mean.

### Confederation assignment

Each of the 48 nations is tagged with its confederation (UEFA / CONMEBOL /
CONCACAF / CAF / AFC / OFC) — small config, derivable from FIFA. The dark-9 by
confederation: UEFA {Bosnia, Norway, Sweden}, CONCACAF {Curaçao, Haiti},
OFC {New Zealand}, AFC {Iraq, Jordan, Uzbekistan}. UEFA/CONCACAF dark sides get a
rich confederation mean; OFC (NZ) has no SB OFC mate → global or hand; AFC dark
sides → hand/global (the structurally dark set, per S26).

## Config schemas

`data/config/coach_continuity.json` (gathered S32):
```jsonc
{
  "_discount": 0.5,              // continuity multiplier when the coach changed
  "rows": {
    "<Nation>|<tournament>": {   // tournament ∈ wc2022|euro2024|copa2024|afcon2023
      "tournament_coach": "...",
      "coach_2026": "...",
      "continuity": 1.0,          // 1.0 same, 0.5 changed
      "source": "https://..."
    }
  }
}
```

Tunables (proposed home: extend `data/config/playstyle_metrics.json` or a new
`d2_blend_params.json`): `rho_wc22=0.5`, `m0=4`, `lambda_max=0.7`,
`tau` (set so a single recent full-tournament row lands λ_team ≈ 0.45–0.55;
calibrate on data), `coach_change_discount=0.5`.

## Open / banked
- Per-axis `λ_max` (v2).
- `τ` calibration target is a judgement call — pin it on the data once the
  evidence sums are computed.
- OFC (New Zealand) and the AFC/Gulf dark set need a hand or global-mean prior
  decision at build time.
