"""
V1.03 residual diagnosis — strength formula vs actual xG.

Frozen exploratory script. Reproduces the residual numbers cited in the
V1.03 methodology notes. Run end-to-end, no CLI args.

Question: does the V1.03 strength formula (sum of starter
shrunk_consistency_eb_class ratings) systematically over- or under-predict
team xG, and which features moderate the error?

Headline findings (n=1500 team-matches, 2024-2025 + 2025-2026 EPL):
  - Global mean residual: -0.990 xG (predicted overshoots actual by ~1.0)
  - Strongest moderator: opponent_avg_xg_allowed
    (0.72 xG residual spread across quintiles)
  - opponent_avg_xg_attack: 0.61 xG spread
  - opponent_avg_PPDA: 0.38 xG spread

Implication: strength formula needs structural redesign to incorporate
opponent defensive and pressing features. See B1.2 design.

Aston Villa anomaly (from earlier session): resolved — not a math floor
issue, just missing defensive features in the formula.
"""
import duckdb
import statistics
from pathlib import Path
from collections import defaultdict

DB_PATH = Path("data/processed/worldcup.duckdb")

MIN_MINUTES_PER_MATCH = 45


def quantile_buckets(values, n_buckets=5):
    """
    Given a list of values, return bucket boundaries (n_buckets-1 cuts).
    Used to split the data into roughly equal-sized buckets.
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    cuts = []
    for i in range(1, n_buckets):
        idx = int(n * i / n_buckets)
        cuts.append(sorted_vals[idx])
    return cuts


def bucket_index(val, cuts):
    """Which bucket does val fall in?"""
    for i, c in enumerate(cuts):
        if val < c:
            return i
    return len(cuts)


def print_bucket_table(label, observations, feature_key, cuts):
    """
    Given observations [{residual:..., feature_key:...}], bin by
    feature_key using cuts, and print bucket stats.
    """
    buckets = defaultdict(list)
    for o in observations:
        b = bucket_index(o[feature_key], cuts)
        buckets[b].append(o["residual"])

    print(f"\n=== {label} ===")
    # Header
    print(f"  {'bucket':<8} {'range':<18} {'n':>4} "
          f"{'mean res':>10} {'sd res':>8} {'median':>8}")
    # Print boundaries
    bnames = []
    prev = "min"
    for c in cuts:
        bnames.append(f"<{c:.3f}")
        prev = f"{c:.3f}"
    bnames.append(f">={cuts[-1]:.3f}")

    for b in sorted(buckets.keys()):
        residuals = buckets[b]
        n = len(residuals)
        mean_r = sum(residuals) / n if n > 0 else 0
        sd_r = (statistics.stdev(residuals) if n >= 2 else 0)
        med_r = statistics.median(residuals) if n > 0 else 0
        # bucket range string
        if b < len(cuts):
            lo = f"<{cuts[b]:.3f}" if b == 0 else f"{cuts[b-1]:.3f}-{cuts[b]:.3f}"
        else:
            lo = f">={cuts[-1]:.3f}"
        print(f"  {b:<8} {lo:<18} {n:>4} "
              f"{mean_r:>+10.3f} {sd_r:>8.3f} {med_r:>+8.3f}")


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Build predicted_xg per (game_id, team) from starter ratings.
        print("=== STEP 1: build predicted_xg per (game_id, team) ===")
        print(f"Starter definition: ≥{MIN_MINUTES_PER_MATCH} min in that match.")
        print(f"Rating: shrunk_consistency_eb_class (V1.03 A4 career-mean).")

        rows = con.execute(
            f"""
            SELECT
                pms.game_id,
                pms.team,
                pms.season,
                SUM(pss.shrunk_consistency_eb_class) AS predicted_xg,
                COUNT(*) AS n_starters
            FROM player_match_stats pms
            JOIN player_season_stats pss
              ON pss.player_id = pms.player_id
             AND pss.season = pms.season
             AND pss.team = pms.team
            WHERE pms.minutes >= {MIN_MINUTES_PER_MATCH}
            GROUP BY pms.game_id, pms.team, pms.season
            """
        ).fetchall()
        predicted_lookup = {}  # (game_id, team) -> predicted_xg
        n_starters_lookup = {}
        for game_id, team, season, pxg, ns in rows:
            predicted_lookup[(game_id, team)] = pxg
            n_starters_lookup[(game_id, team)] = ns
        print(f"  Built predictions for {len(predicted_lookup)} team-matches.")

        # Diagnostic: starter counts per match (should be close to 11).
        from collections import Counter
        ns_counter = Counter(n_starters_lookup.values())
        print(f"  Starter count distribution:")
        for ns in sorted(ns_counter.keys()):
            print(f"    {ns} starters: {ns_counter[ns]} team-matches")

        # 2. Compute opponent season-aggregate features.
        print("\n=== STEP 2: opponent season-aggregate features ===")
        # avg PPDA, avg opponent_xg (defensive baseline), avg own xg
        # (attacking strength), per (team, season).
        team_features = {}
        for r in con.execute(
            """
            SELECT
                team, season,
                AVG(ppda) AS avg_ppda,
                AVG(opponent_xg) AS avg_opp_xg_allowed,
                AVG(xg) AS avg_xg
            FROM team_match_stats
            GROUP BY team, season
            """
        ).fetchall():
            team_features[(r[0], r[1])] = {
                "avg_ppda": r[2],
                "avg_opp_xg_allowed": r[3],
                "avg_xg": r[4],
            }
        print(f"  Built features for {len(team_features)} "
              f"(team, season) combos.")

        # 3. Join everything into per-team-match observations.
        print("\n=== STEP 3: assemble observations ===")
        obs = []  # one per (game, team) where we have all data
        skipped = 0
        for r in con.execute(
            """
            SELECT
                game_id, team, opponent, season, xg, side
            FROM team_match_stats
            """
        ).fetchall():
            game_id, team, opp, season, actual_xg, side = r
            pred = predicted_lookup.get((game_id, team))
            opp_feat = team_features.get((opp, season))
            if pred is None or opp_feat is None:
                skipped += 1
                continue
            obs.append({
                "game_id": game_id,
                "team": team,
                "opponent": opp,
                "season": season,
                "side": side,
                "actual_xg": actual_xg,
                "predicted_xg": pred,
                "residual": actual_xg - pred,
                "opp_ppda": opp_feat["avg_ppda"],
                "opp_xg_allowed": opp_feat["avg_opp_xg_allowed"],
                "opp_xg_attack": opp_feat["avg_xg"],
            })
        print(f"  Assembled {len(obs)} observations.")
        print(f"  Skipped {skipped} (missing predictions or opponent data).")

        # 4. Overall residual stats.
        residuals = [o["residual"] for o in obs]
        predicteds = [o["predicted_xg"] for o in obs]
        actuals = [o["actual_xg"] for o in obs]
        print(f"\n=== STEP 4: overall residual stats ===")
        print(f"  mean residual    = "
              f"{sum(residuals)/len(residuals):+.3f}")
        print(f"  sd residual      = "
              f"{statistics.stdev(residuals):.3f}")
        print(f"  mean predicted   = "
              f"{sum(predicteds)/len(predicteds):.3f}")
        print(f"  mean actual      = "
              f"{sum(actuals)/len(actuals):.3f}")
        # Pearson r as a single-number sanity check.
        pred_mean = sum(predicteds)/len(predicteds)
        act_mean  = sum(actuals)/len(actuals)
        cov = sum((p - pred_mean) * (a - act_mean)
                  for p, a in zip(predicteds, actuals)) / len(predicteds)
        var_p = sum((p - pred_mean)**2 for p in predicteds) / len(predicteds)
        var_a = sum((a - act_mean)**2 for a in actuals) / len(actuals)
        r = cov / (var_p**0.5 * var_a**0.5) if var_p > 0 and var_a > 0 else 0
        print(f"  Pearson r (pred, actual) = {r:.3f}  "
              f"(note: contaminated by leakage; treat as upper bound)")

        # 5. Bucket residuals by each feature.
        # Use quintiles (5 buckets) of each feature.

        # 5a. predicted_xg buckets (the B1 concern — does linear model
        # break at extremes?)
        cuts = quantile_buckets([o["predicted_xg"] for o in obs], 5)
        print_bucket_table(
            "Residual by predicted_xg quintile "
            "(B1 concern: extremes)",
            obs, "predicted_xg", cuts,
        )

        # 5b. opponent PPDA buckets
        cuts = quantile_buckets([o["opp_ppda"] for o in obs], 5)
        print_bucket_table(
            "Residual by opponent_avg_PPDA quintile "
            "(low PPDA = high press; do residuals drop?)",
            obs, "opp_ppda", cuts,
        )

        # 5c. opponent defensive baseline (xg allowed)
        cuts = quantile_buckets([o["opp_xg_allowed"] for o in obs], 5)
        print_bucket_table(
            "Residual by opponent_avg_xg_allowed quintile "
            "(leaky defenses = higher xg against; do residuals shift?)",
            obs, "opp_xg_allowed", cuts,
        )

        # 5d. opponent attacking strength
        cuts = quantile_buckets([o["opp_xg_attack"] for o in obs], 5)
        print_bucket_table(
            "Residual by opponent_avg_xg_attack quintile "
            "(strong attackers may be weaker defenders?)",
            obs, "opp_xg_attack", cuts,
        )

        # 6. Home vs away split — does HOME_BONUS need recalibration?
        print(f"\n=== STEP 5: home vs away residual split ===")
        home_obs = [o for o in obs if o["side"] == "home"]
        away_obs = [o for o in obs if o["side"] == "away"]
        for label, sub in [("home", home_obs), ("away", away_obs)]:
            res = [o["residual"] for o in sub]
            mean_r = sum(res)/len(res)
            print(f"  {label:<5} n={len(sub):>4} "
                  f"mean_residual={mean_r:+.3f}")
        # If home mean residual > 0 and away mean residual < 0, current
        # HOME_BONUS is too small — actual home advantage is bigger.

        # 7. Spotlight on extreme cases — top/bottom 10 by residual.
        print(f"\n=== STEP 6: spotlight on extreme residuals ===")
        obs_sorted = sorted(obs, key=lambda o: o["residual"])

        print(f"\nBottom 8 (largest UNDERPERFORMANCE — predicted high, "
              f"actual low):")
        print(f"  {'team':<22} vs {'opp':<22} "
              f"{'pred':>5} {'actual':>6} {'resid':>6} "
              f"{'opp_PPDA':>8} {'opp_xgA':>8}")
        for o in obs_sorted[:8]:
            print(f"  {o['team'][:22]:<22} vs {o['opponent'][:22]:<22} "
                  f"{o['predicted_xg']:>5.2f} {o['actual_xg']:>6.2f} "
                  f"{o['residual']:>+6.2f} "
                  f"{o['opp_ppda']:>8.2f} {o['opp_xg_allowed']:>8.2f}")

        print(f"\nTop 8 (largest OVERPERFORMANCE — predicted low, "
              f"actual high):")
        for o in obs_sorted[-8:][::-1]:
            print(f"  {o['team'][:22]:<22} vs {o['opponent'][:22]:<22} "
                  f"{o['predicted_xg']:>5.2f} {o['actual_xg']:>6.2f} "
                  f"{o['residual']:>+6.2f} "
                  f"{o['opp_ppda']:>8.2f} {o['opp_xg_allowed']:>8.2f}")

        # 8. Sanity check — Manchester City vs Aston Villa, both directions
        print(f"\n=== STEP 7: Aston Villa & Man City matchup spotlight ===")
        print(f"(S9 B1 concern: linear model predicted Villa 0.22 xG vs City)")
        for r in con.execute(
            """
            SELECT
                tms.team, tms.opponent, tms.season, tms.xg AS actual_xg,
                tms.opponent_xg AS opp_actual_xg
            FROM team_match_stats tms
            WHERE (tms.team = 'Manchester City' AND tms.opponent = 'Aston Villa')
               OR (tms.team = 'Aston Villa' AND tms.opponent = 'Manchester City')
            ORDER BY tms.season, tms.game_id
            """
        ).fetchall():
            team, opp, season, axg, opp_axg = r
            print(f"  {season}  {team:<18} vs {opp:<18} "
                  f"actual={axg:.2f}  opp_actual={opp_axg:.2f}")
    finally:
        con.close()


if __name__ == "__main__":
    main()