"""
V1.03 modeling — STEP 6 (A4): per-position-class prior + per-bucket k.

WHAT THIS DOES
    Replaces V1.03 A3's single league-wide prior + global k with
    per-bucket priors AND per-bucket empirical k values, using A6's
    V1.03 6-tier class structure (collapsed to 4 buckets for prior
    stability).

THE 4 PRIOR BUCKETS (S11 lock)
    A6 produced a 6-tier class structure (GK / DEF / DEF-MID /
    CENTRAL-MID / ATT-MID / FWD). For prior calculation, we collapse
    to 4 buckets to ensure enough players per bucket:
      1. GK              — use league mean (0.2390) fallback, ~28 players
      2. DEF             — own bucket, ~149 players
      3. MID-combined    — DEF-MID + CENTRAL-MID, ~84 players
      4. ATT-combined    — ATT-MID + FWD, ~135 players

    GK gets the league-mean fallback because:
      (a) only ~28 players, small sample
      (b) GK rating_per_90 is near-zero anyway, prior barely matters

THE FORMULAS
    For each bucket:
        prior_bucket = minutes-weighted mean of rating_per_90
                       across players whose primary_position_class_v103
                       falls in this bucket

        σ²_within_bucket = avg of per-player variance in per-match
                           rating_per_90 (≥45 min, ≥10 matches),
                           restricted to bucket members

        σ²_between_bucket = variance of career means across bucket members

        k_bucket = σ²_within_bucket / σ²_between_bucket    (in MATCH units)

    For each player_season_stats row:
        Look up player's bucket from primary_position_class_v103
        Use that bucket's k and prior:
            w = n_matches / (n_matches + k_bucket)
            shrunk_form_eb_class = w * rating_per_90 + (1-w) * prior_bucket
            (same for shrunk_consistency_eb_class with career_mean)

DEPENDENCY ON A6
    Requires primary_position_class_v103 column on player_season_stats
    (populated by fine_grained_position.py). Each player's bucket is
    determined by their A6-derived V1.03 class.

WHAT WE STORE
    Two new columns on player_season_stats:
        shrunk_form_eb_class
        shrunk_consistency_eb_class
    Plus we print all 4 bucket priors + per-bucket k values for the
    record. Future work could store these in a calibration_params
    table; for V1.03 they're just logged.

KNOWN LIMITATIONS
    1. σ²_between is biased upward (career means are noisy estimates).
       Skipped correction — same as A3.
    2. GK bucket uses league-mean fallback. Could overshrink GK ratings
       toward FWD-dominated 0.239; but GK ratings are ~0 anyway so
       shrinkage outcome ≈ 0 either way.
    3. The 4-bucket collapse is judgment, not data-derived. Future
       work could derive bucket boundaries from clustering.

HOW TO RUN
    From the repo root:
        uv run python src/model/per_class_prior_shrinkage.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

PRIOR_LEAGUE_FALLBACK = 0.2390  # V1.02 prior, used for GK
MIN_MINUTES_PER_MATCH = 45
MIN_MATCHES_PER_PLAYER = 10

# V1.03 6-tier class -> bucket name (4 buckets for prior calc)
CLASS_TO_BUCKET = {
    "GK":          "GK",
    "DEF":         "DEF",
    "DEF-MID":     "MID",
    "CENTRAL-MID": "MID",
    "ATT-MID":     "ATT",
    "FWD":         "ATT",
}


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Verify A6 has run (primary_position_class_v103 exists).
        cols = {
            r[0] for r in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }
        if "primary_position_class_v103" not in cols:
            raise SystemExit(
                "primary_position_class_v103 missing. Run A6 first "
                "(src/model/fine_grained_position.py)."
            )

        # 2. Add new columns if missing.
        for new_col in ("shrunk_form_eb_class", "shrunk_consistency_eb_class"):
            if new_col not in cols:
                print(f"Adding column {new_col}...")
                con.execute(
                    f"ALTER TABLE player_season_stats "
                    f"ADD COLUMN {new_col} DOUBLE"
                )

        # 3. Build (player_id, bucket) lookup.
        # Each player_season_stats row has primary_position_class_v103;
        # map to bucket via CLASS_TO_BUCKET.
        # A player may have different classes in different seasons,
        # but we're computing per-(player, season, team) shrinkage, so
        # bucket lookup keys on (player_id, season, team).
        pss_rows = con.execute(
            """
            SELECT player_id, season, team, primary_position_class_v103
            FROM player_season_stats
            """
        ).fetchall()
        bucket_lookup = {}  # (pid, season, team) -> bucket
        unmapped_classes = set()
        for pid, season, team, cls in pss_rows:
            bucket = CLASS_TO_BUCKET.get(cls)
            if bucket is None:
                unmapped_classes.add(cls)
                continue
            bucket_lookup[(pid, season, team)] = bucket
        if unmapped_classes:
            raise SystemExit(
                f"Classes not in CLASS_TO_BUCKET: {unmapped_classes}"
            )
        print(f"\n=== STEP 1: bucket membership ===")
        from collections import Counter
        bucket_counts = Counter(bucket_lookup.values())
        for b in ("GK", "DEF", "MID", "ATT"):
            print(f"  {b:<6}  {bucket_counts.get(b, 0):>4} player-season rows")

        # 4. Compute per-bucket prior (minutes-weighted mean of
        # rating_per_90 across bucket's player-season rows).
        print(f"\n=== STEP 2: per-bucket priors (minutes-weighted) ===")
        # We need to compute this in SQL, joining to bucket via the
        # primary_position_class_v103. Build the bucket prior dict.
        bucket_priors = {}
        for bucket_label, classes in [
            ("DEF", ("DEF",)),
            ("MID", ("DEF-MID", "CENTRAL-MID")),
            ("ATT", ("ATT-MID", "FWD")),
        ]:
            placeholders = ",".join(["?"] * len(classes))
            r = con.execute(
                f"""
                SELECT
                    SUM(rating_per_90 * minutes) / SUM(minutes)
                        AS minutes_weighted_mean,
                    COUNT(*) AS n_rows,
                    SUM(minutes) AS total_min
                FROM player_season_stats
                WHERE primary_position_class_v103 IN ({placeholders})
                """,
                list(classes),
            ).fetchone()
            mean, n, total_min = r
            bucket_priors[bucket_label] = mean
            print(f"  {bucket_label:<6}  prior = {mean:.4f}  "
                  f"(from {n} rows, {total_min} total min)")

        # GK gets the league fallback.
        bucket_priors["GK"] = PRIOR_LEAGUE_FALLBACK
        print(f"  GK    prior = {PRIOR_LEAGUE_FALLBACK:.4f}  "
              f"(league fallback, small sample)")

        # 5. Compute per-bucket σ²_within.
        # For each bucket, identify which players are in that bucket
        # (via primary_position_class_v103), then compute σ²_within
        # over their per-match data.
        print(f"\n=== STEP 3: per-bucket σ²_within ===")
        bucket_sigma_within = {}
        for bucket_label, classes in [
            ("DEF", ("DEF",)),
            ("MID", ("DEF-MID", "CENTRAL-MID")),
            ("ATT", ("ATT-MID", "FWD")),
        ]:
            placeholders = ",".join(["?"] * len(classes))
            # σ²_within for this bucket: avg of per-player variance,
            # restricted to players whose primary V1.03 class falls in
            # the bucket (using ANY pss row to identify; a player's
            # class can be stable across seasons or change, so we use
            # 'in any season' membership).
            r = con.execute(
                f"""
                WITH bucket_players AS (
                    SELECT DISTINCT player_id
                    FROM player_season_stats
                    WHERE primary_position_class_v103 IN ({placeholders})
                ),
                match_ratings AS (
                    SELECT
                        pms.player_id,
                        (pms.xg + pms.xa) * 90.0 / pms.minutes
                            AS rating_per_90
                    FROM player_match_stats pms
                    JOIN bucket_players bp ON bp.player_id = pms.player_id
                    WHERE pms.minutes >= ?
                ),
                per_player AS (
                    SELECT
                        player_id,
                        COUNT(*) AS n_matches,
                        VARIANCE(rating_per_90) AS player_variance
                    FROM match_ratings
                    GROUP BY player_id
                    HAVING COUNT(*) >= ?
                )
                SELECT
                    AVG(player_variance),
                    COUNT(*),
                    AVG(n_matches)
                FROM per_player
                """,
                list(classes) + [MIN_MINUTES_PER_MATCH,
                                 MIN_MATCHES_PER_PLAYER],
            ).fetchone()
            sigma2, n_players, avg_n = r
            bucket_sigma_within[bucket_label] = sigma2
            print(f"  {bucket_label:<6}  σ²_within = {sigma2:.6f}  "
                  f"(from {n_players} players, {avg_n:.1f} matches/player avg)")

        # GK σ²_within: compute it too, for transparency.
        r = con.execute(
            """
            WITH bucket_players AS (
                SELECT DISTINCT player_id
                FROM player_season_stats
                WHERE primary_position_class_v103 = 'GK'
            ),
            match_ratings AS (
                SELECT
                    pms.player_id,
                    (pms.xg + pms.xa) * 90.0 / pms.minutes AS rating_per_90
                FROM player_match_stats pms
                JOIN bucket_players bp ON bp.player_id = pms.player_id
                WHERE pms.minutes >= ?
            ),
            per_player AS (
                SELECT
                    player_id,
                    COUNT(*) AS n_matches,
                    VARIANCE(rating_per_90) AS player_variance
                FROM match_ratings
                GROUP BY player_id
                HAVING COUNT(*) >= ?
            )
            SELECT
                AVG(player_variance), COUNT(*), AVG(n_matches)
            FROM per_player
            """,
            [MIN_MINUTES_PER_MATCH, MIN_MATCHES_PER_PLAYER],
        ).fetchone()
        if r[0] is not None:
            bucket_sigma_within["GK"] = r[0]
            print(f"  GK    σ²_within = {r[0]:.6f}  "
                  f"(from {r[1]} players, {r[2]:.1f} matches/player avg) "
                  f"[diagnostic only]")
        else:
            bucket_sigma_within["GK"] = None
            print(f"  GK    σ²_within = NULL "
                  f"(too few GKs with ≥{MIN_MATCHES_PER_PLAYER} matches)")

        # 6. Compute per-bucket σ²_between.
        print(f"\n=== STEP 4: per-bucket σ²_between ===")
        bucket_sigma_between = {}
        for bucket_label, classes in [
            ("DEF", ("DEF",)),
            ("MID", ("DEF-MID", "CENTRAL-MID")),
            ("ATT", ("ATT-MID", "FWD")),
        ]:
            placeholders = ",".join(["?"] * len(classes))
            r = con.execute(
                f"""
                WITH bucket_players AS (
                    SELECT DISTINCT player_id
                    FROM player_season_stats
                    WHERE primary_position_class_v103 IN ({placeholders})
                ),
                career_means AS (
                    SELECT
                        pss.player_id,
                        SUM(pss.rating_per_90 * pss.minutes)
                            / SUM(pss.minutes) AS career_mean
                    FROM player_season_stats pss
                    JOIN bucket_players bp ON bp.player_id = pss.player_id
                    GROUP BY pss.player_id
                )
                SELECT VARIANCE(career_mean), COUNT(*) FROM career_means
                """,
                list(classes),
            ).fetchone()
            sigma2, n_players = r
            bucket_sigma_between[bucket_label] = sigma2
            print(f"  {bucket_label:<6}  σ²_between = {sigma2:.6f}  "
                  f"(across {n_players} players)")

        # 7. Compute per-bucket k.
        print(f"\n=== STEP 5: per-bucket empirical k ===")
        bucket_k = {}
        for bucket_label in ("DEF", "MID", "ATT"):
            sigma2_w = bucket_sigma_within[bucket_label]
            sigma2_b = bucket_sigma_between[bucket_label]
            if sigma2_b is None or sigma2_b <= 0 or sigma2_w is None:
                raise SystemExit(
                    f"Cannot compute k for {bucket_label}: "
                    f"σ²_within={sigma2_w}, σ²_between={sigma2_b}"
                )
            k = sigma2_w / sigma2_b
            bucket_k[bucket_label] = k
            print(f"  k_{bucket_label} = {sigma2_w:.6f} / {sigma2_b:.6f} "
                  f"= {k:.2f} matches")

        # GK k — use global A3 k=2.25 as fallback. The script's reasoning
        # is: GK shrinkage barely matters anyway, league mean prior,
        # global k. Diagnostic if it differs.
        bucket_k["GK"] = 2.25
        print(f"  k_GK = 2.25 matches (A3 global k fallback for GK; "
              f"GK shrinkage barely affects outcomes)")

        # 8. Pre-compute match counts per (player, season, team) and
        # career (same as A3 fix).
        print(f"\n=== STEP 6: per-(player,season,team) match counts ===")
        season_match_count = {
            (r[0], r[1], r[2]): r[3] for r in con.execute(
                """
                SELECT player_id, season, team, COUNT(*) AS n_matches
                FROM player_match_stats
                WHERE minutes >= ?
                GROUP BY player_id, season, team
                """,
                [MIN_MINUTES_PER_MATCH],
            ).fetchall()
        }
        career_match_count = {
            r[0]: r[1] for r in con.execute(
                """
                SELECT player_id, COUNT(*) AS n_matches
                FROM player_match_stats
                WHERE minutes >= ?
                GROUP BY player_id
                """,
                [MIN_MINUTES_PER_MATCH],
            ).fetchall()
        }
        print(f"  Counted matches for "
              f"{len(season_match_count)} season-team combos and "
              f"{len(career_match_count)} career players.")

        # 9. Apply per-bucket shrinkage.
        print(f"\n=== STEP 7: apply per-bucket k + prior ===")

        # Pre-fetch all rows + career means.
        pss_full = con.execute(
            """
            WITH career AS (
                SELECT
                    player_id,
                    SUM(rating_per_90 * minutes) / SUM(minutes)
                        AS career_mean
                FROM player_season_stats
                GROUP BY player_id
            )
            SELECT
                pss.player_id, pss.season, pss.team,
                pss.rating_per_90,
                c.career_mean,
                pss.primary_position_class_v103
            FROM player_season_stats pss
            JOIN career c ON c.player_id = pss.player_id
            """
        ).fetchall()

        update_rows = []
        for pid, season, team, raw, career_mean, v103_class in pss_full:
            bucket = CLASS_TO_BUCKET[v103_class]
            prior = bucket_priors[bucket]
            k = bucket_k[bucket]
            n_season = season_match_count.get(
                (pid, season, team), 0
            )
            n_career = career_match_count.get(pid, 0)

            w_season = n_season / (n_season + k) if n_season > 0 else 0.0
            shrunk_form_eb_class = (
                w_season * raw + (1 - w_season) * prior
            )

            w_career = n_career / (n_career + k) if n_career > 0 else 0.0
            shrunk_consistency_eb_class = (
                w_career * career_mean + (1 - w_career) * prior
            )

            update_rows.append((
                shrunk_form_eb_class, shrunk_consistency_eb_class,
                pid, season, team,
            ))
        print(f"  Built {len(update_rows)} update rows.")

        con.execute("BEGIN TRANSACTION")
        try:
            con.executemany(
                """
                UPDATE player_season_stats
                SET shrunk_form_eb_class = ?,
                    shrunk_consistency_eb_class = ?
                WHERE player_id = ? AND season = ? AND team = ?
                """,
                update_rows,
            )
            nulls = con.execute("""
                SELECT
                    SUM(shrunk_form_eb_class IS NULL),
                    SUM(shrunk_consistency_eb_class IS NULL),
                    COUNT(*)
                FROM player_season_stats
            """).fetchone()
            print(f"  NULL counts: form_eb_class={nulls[0]}, "
                  f"consistency_eb_class={nulls[1]} (of {nulls[2]} rows)")
            con.execute("COMMIT")
            print("  COMMITTED.")
        except Exception:
            print("!!! Rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 10. Sanity outputs.
        print(f"\n=== STEP 8: comparison across all shrinkage versions ===")

        # Distribution stats per bucket.
        print(f"\n--- 2025-2026 averages by V1.03 class, all 4 versions ---")
        print(f"  {'class':<14} "
              f"{'n':>4} "
              f"{'raw':>7} "
              f"{'V1.02':>7} "
              f"{'A3 eb':>7} "
              f"{'A4 eb_cls':>10}")
        for r in con.execute(
            """
            SELECT
                primary_position_class_v103,
                COUNT(*) AS n,
                AVG(rating_per_90) AS raw,
                AVG(shrunk_form)   AS v102,
                AVG(shrunk_form_eb) AS a3,
                AVG(shrunk_form_eb_class) AS a4
            FROM player_season_stats
            WHERE season = '2025-2026'
            GROUP BY primary_position_class_v103
            ORDER BY raw DESC
            """
        ).fetchall():
            print(f"  {r[0]:<14} {r[1]:>4} "
                  f"{r[2]:>7.3f} {r[3]:>7.3f} {r[4]:>7.3f} {r[5]:>10.3f}")

        # Top players: how do all 4 columns differ?
        print(f"\n--- Top 10 by V1.02 shrunk_form (2025-2026) ---")
        print(f"  {'player':<24} {'cls':<12} "
              f"{'raw':>6} {'V1.02':>6} {'A3':>6} {'A4':>6}")
        for r in con.execute(
            """
            SELECT
                p.player_name, pss.primary_position_class_v103,
                pss.rating_per_90, pss.shrunk_form,
                pss.shrunk_form_eb, pss.shrunk_form_eb_class
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '2025-2026'
            ORDER BY pss.shrunk_form DESC NULLS LAST
            LIMIT 10
            """
        ).fetchall():
            print(f"  {r[0][:24]:<24} {r[1][:12]:<12} "
                  f"{r[2]:>6.3f} {r[3]:>6.3f} {r[4]:>6.3f} {r[5]:>6.3f}")

        # Low-minute spotlight to see how shrinkage varies.
        print(f"\n--- Low-minute players (500-1000 min), top raw ratings ---")
        print(f"  {'player':<24} {'cls':<12} "
              f"{'raw':>6} {'V1.02':>6} {'A3':>6} {'A4':>6}")
        for r in con.execute(
            """
            SELECT
                p.player_name, pss.primary_position_class_v103,
                pss.rating_per_90, pss.shrunk_form,
                pss.shrunk_form_eb, pss.shrunk_form_eb_class
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '2025-2026'
              AND pss.minutes BETWEEN 500 AND 1000
            ORDER BY pss.rating_per_90 DESC
            LIMIT 8
            """
        ).fetchall():
            print(f"  {r[0][:24]:<24} {r[1][:12]:<12} "
                  f"{r[2]:>6.3f} {r[3]:>6.3f} {r[4]:>6.3f} {r[5]:>6.3f}")

        # Print the calibration summary at the end for record-keeping.
        print(f"\n=== CALIBRATION SUMMARY (V1.03 A4) ===")
        print(f"  {'bucket':<10} {'prior':>8} {'k':>8} "
              f"{'σ²_within':>12} {'σ²_between':>13}")
        for b in ("GK", "DEF", "MID", "ATT"):
            sw = bucket_sigma_within.get(b)
            sb = bucket_sigma_between.get(b)
            sw_str = f"{sw:.6f}" if sw is not None else "(skip)"
            sb_str = f"{sb:.6f}" if sb is not None else "(skip)"
            print(f"  {b:<10} {bucket_priors[b]:>8.4f} "
                  f"{bucket_k[b]:>8.2f} "
                  f"{sw_str:>12} {sb_str:>13}")
    finally:
        con.close()


if __name__ == "__main__":
    main()