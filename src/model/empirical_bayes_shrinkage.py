"""
V1.03 modeling — STEP 4 (A3): empirical Bayes shrinkage (FIXED).

WHAT CHANGED FROM FIRST ATTEMPT
    The first attempt computed k_empirical = σ²_within / σ²_between =
    ~2.3, then applied it with `w = minutes / (minutes + k)`. This made
    w ≈ 0.999 for everyone — essentially no shrinkage at all (e.g.,
    Zirkzee's rating snapped back to 0.81 raw, undoing V1.02's fix).

    The unit mismatch: k = σ²_within / σ²_between is in MATCH units
    (because σ²_within is "variance per per-match observation"). But
    the shrinkage formula was applied against MINUTES.

    Fix: count qualifying matches per (player, season, team) and use
    that as the sample size:
        w = n_matches / (n_matches + k)

    This is the classical empirical Bayes shrinkage. The math now
    matches the units.

WHAT THIS DOES
    Replaces V1.02's heuristic k=900 (minutes) with empirical k (matches)
    computed from per-match variance analysis. Overwrites the
    shrunk_form_eb and shrunk_consistency_eb columns (which contained
    junk from the first attempt). V1.02's shrunk_form and
    shrunk_consistency columns remain untouched.

THE MATH (now consistent)
    For each (player, season, team) row:
        n_matches  = count of player's ≥45-min matches in that season
        w          = n_matches / (n_matches + k_empirical)
        shrunk_eb  = w * observed + (1 - w) * prior

    where:
        k_empirical = σ²_within / σ²_between
        σ²_within   = avg per-player variance in per-match rating_per_90
                      (≥45-min matches, ≥10 matches per player for inclusion)
        σ²_between  = variance of player career-mean rating_per_90s

WHY MATCH COUNT AS SAMPLE SIZE
    The empirical Bayes formula assumes the units of k align with the
    units of sample size. Since σ²_within is computed per match, k is
    in match units. Sample size must be in match units too — hence
    n_matches, not minutes.

SHRUNK_CONSISTENCY_EB note
    V1.02's shrunk_consistency uses career-weighted aggregate then
    shrinks once. We mirror: career_mean (minutes-weighted across all
    seasons) + total qualifying match count across all seasons as the
    sample size for that player's shrinkage.

HOW TO RUN
    From the repo root:
        uv run python src/model/empirical_bayes_shrinkage.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# Carried from V1.02 for direct comparability.
PRIOR = 0.2390

# S11 design parameters.
MIN_MINUTES_PER_MATCH = 45    # ≥45-min match counts as a real appearance
MIN_MATCHES_PER_PLAYER = 10   # min matches to include player in σ²_within


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Verify prerequisites.
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for required in ("player_season_stats", "player_match_stats"):
            if required not in existing:
                raise SystemExit(
                    f"Required table '{required}' missing."
                )

        # 2. Add columns if missing. Idempotent.
        existing_cols = {
            r[0] for r in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }
        for new_col in ("shrunk_form_eb", "shrunk_consistency_eb"):
            if new_col not in existing_cols:
                print(f"Adding column {new_col}...")
                con.execute(
                    f"ALTER TABLE player_season_stats "
                    f"ADD COLUMN {new_col} DOUBLE"
                )

        # 3. Compute σ²_within from per-match data.
        print("\n=== STEP 1: σ²_within from per-match data ===")
        print(f"Filter: minutes >= {MIN_MINUTES_PER_MATCH}, "
              f"player must have >= {MIN_MATCHES_PER_PLAYER} qualifying matches")

        sigma2_within, n_within_players, avg_matches = con.execute(
            """
            WITH match_ratings AS (
                SELECT
                    player_id,
                    (xg + xa) * 90.0 / minutes AS rating_per_90
                FROM player_match_stats
                WHERE minutes >= ?
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
            [MIN_MINUTES_PER_MATCH, MIN_MATCHES_PER_PLAYER],
        ).fetchone()

        if sigma2_within is None:
            raise SystemExit("σ²_within computed as NULL.")

        print(f"  σ²_within = {sigma2_within:.6f}")
        print(f"  Estimated from {n_within_players} players "
              f"({avg_matches:.1f} matches/player avg)")

        # 4. Compute σ²_between.
        print("\n=== STEP 2: σ²_between from career means ===")
        sigma2_between, n_between_players = con.execute(
            """
            WITH career_means AS (
                SELECT
                    player_id,
                    SUM(rating_per_90 * minutes) / SUM(minutes)
                        AS career_mean
                FROM player_season_stats
                GROUP BY player_id
            )
            SELECT VARIANCE(career_mean), COUNT(*) FROM career_means
            """
        ).fetchone()
        print(f"  σ²_between = {sigma2_between:.6f}")
        print(f"  Computed across {n_between_players} unique players")

        # 5. Compute k_empirical (in MATCH units this time).
        if sigma2_between is None or sigma2_between <= 0:
            raise SystemExit(
                f"σ²_between is non-positive ({sigma2_between})."
            )
        k_empirical = sigma2_within / sigma2_between

        print(f"\n=== STEP 3: empirical k (in MATCH units) ===")
        print(f"  k_empirical = σ²_within / σ²_between = "
              f"{sigma2_within:.6f} / {sigma2_between:.6f}")
        print(f"  k_empirical = {k_empirical:.2f} matches")
        print(f"  (Compare to V1.02 heuristic k=900 MINUTES, "
              f"equivalent to ~10 full matches)")

        # 6. Pre-compute match counts per (player, season, team) and per
        # player career — needed for the shrinkage formula.
        # n_matches_season: how many ≥45-min matches in that season
        # n_matches_career: how many ≥45-min matches across all seasons
        print(f"\n=== STEP 4: count qualifying matches per "
              f"(player, season, team) ===")
        match_counts_rows = con.execute(
            """
            SELECT
                player_id, season, team,
                COUNT(*) AS n_matches_season
            FROM player_match_stats
            WHERE minutes >= ?
            GROUP BY player_id, season, team
            """,
            [MIN_MINUTES_PER_MATCH],
        ).fetchall()
        season_match_count = {
            (r[0], r[1], r[2]): r[3] for r in match_counts_rows
        }
        print(f"  Counted matches for "
              f"{len(season_match_count)} (player, season, team) "
              f"rows.")

        career_counts_rows = con.execute(
            """
            SELECT
                player_id,
                COUNT(*) AS n_matches_career
            FROM player_match_stats
            WHERE minutes >= ?
            GROUP BY player_id
            """,
            [MIN_MINUTES_PER_MATCH],
        ).fetchall()
        career_match_count = {r[0]: r[1] for r in career_counts_rows}
        print(f"  Counted career matches for "
              f"{len(career_match_count)} unique players.")

        # 7. Apply shrinkage. For each player_season_stats row:
        #    - n_matches_season for shrunk_form_eb
        #    - n_matches_career for shrunk_consistency_eb (career mean
        #      shrunk by the player's total career match count)
        print(f"\n=== STEP 5: apply k={k_empirical:.2f} matches ===")

        # First fetch all pss rows + needed inputs.
        pss_rows = con.execute(
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
                c.career_mean
            FROM player_season_stats pss
            JOIN career c ON c.player_id = pss.player_id
            """
        ).fetchall()

        # Compute new shrunk values per row.
        update_rows = []  # (form_eb, consistency_eb, player_id, season, team)
        missing_season_match_count = 0
        missing_career_match_count = 0
        for player_id, season, team, raw_rating, career_mean in pss_rows:
            n_season = season_match_count.get(
                (player_id, season, team), 0
            )
            n_career = career_match_count.get(player_id, 0)

            # Edge case: a player might have a season row but ZERO
            # ≥45-min matches in that season (got all their minutes in
            # short subs). w = 0/(0+k) = 0 → fully shrunk to prior.
            # This is actually correct behavior — they have no usable
            # observations under our quality bar.
            if n_season == 0:
                missing_season_match_count += 1
            if n_career == 0:
                missing_career_match_count += 1

            w_season = n_season / (n_season + k_empirical) if n_season > 0 else 0.0
            shrunk_form_eb = w_season * raw_rating + (1 - w_season) * PRIOR

            w_career = n_career / (n_career + k_empirical) if n_career > 0 else 0.0
            shrunk_consistency_eb = (
                w_career * career_mean + (1 - w_career) * PRIOR
            )

            update_rows.append((
                shrunk_form_eb, shrunk_consistency_eb,
                player_id, season, team,
            ))

        print(f"  Built {len(update_rows)} update rows.")
        if missing_season_match_count > 0:
            print(f"  WARNING: {missing_season_match_count} rows have "
                  f"0 ≥45-min matches → shrunk_form_eb fully = prior.")
        if missing_career_match_count > 0:
            print(f"  WARNING: {missing_career_match_count} rows have "
                  f"0 career ≥45-min matches → shrunk_consistency_eb "
                  f"fully = prior.")

        # 8. Write in a transaction.
        con.execute("BEGIN TRANSACTION")
        try:
            con.executemany(
                """
                UPDATE player_season_stats
                SET shrunk_form_eb = ?, shrunk_consistency_eb = ?
                WHERE player_id = ? AND season = ? AND team = ?
                """,
                update_rows,
            )

            # Verify no NULL in the new columns.
            nulls = con.execute("""
                SELECT
                    SUM(shrunk_form_eb IS NULL),
                    SUM(shrunk_consistency_eb IS NULL),
                    COUNT(*)
                FROM player_season_stats
            """).fetchone()
            print(f"\n  NULL counts: form_eb={nulls[0]}, "
                  f"consistency_eb={nulls[1]} (of {nulls[2]} rows)")

            con.execute("COMMIT")
            print("  COMMITTED.")
        except Exception:
            print("!!! Rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 9. Sanity outputs.
        print(f"\n=== STEP 6: V1.02 vs V1.03 sanity comparison ===")

        # Top 10 by V1.02 shrunk_form.
        print(f"\n--- Top 10 by V1.02 shrunk_form (2025-2026) ---")
        print(f"  {'player':<26} {'team':<16} "
              f"{'min':>5} {'n45+':>5} {'raw':>6} "
              f"{'V1.02 form':>10} {'V1.03 form':>10} {'Δ':>7}")
        for r in con.execute(
            """
            SELECT
                p.player_name, pss.team, pss.minutes,
                COALESCE(mc.n_match, 0) AS n_match,
                pss.rating_per_90,
                pss.shrunk_form,
                pss.shrunk_form_eb
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            LEFT JOIN (
                SELECT player_id, season, team, COUNT(*) AS n_match
                FROM player_match_stats
                WHERE minutes >= 45
                GROUP BY player_id, season, team
            ) mc
              ON mc.player_id = pss.player_id
             AND mc.season = pss.season
             AND mc.team = pss.team
            WHERE pss.season = '2025-2026'
            ORDER BY pss.shrunk_form DESC NULLS LAST
            LIMIT 10
            """
        ).fetchall():
            name, team, mins, nmatch, raw, sf, sf_eb = r
            delta = sf_eb - sf
            print(f"  {name[:26]:<26} {team[:16]:<16} "
                  f"{mins:>5} {nmatch:>5} {raw:>6.3f} "
                  f"{sf:>10.3f} {sf_eb:>10.3f} {delta:>+7.3f}")

        # Low-minute spotlight — small-sample inflation cases.
        print(f"\n--- Low-minute players (500-1000 min, 2025-2026) "
              f"sorted by raw rating DESC ---")
        print(f"  {'player':<26} {'team':<16} "
              f"{'min':>5} {'n45+':>5} {'raw':>6} "
              f"{'V1.02 form':>10} {'V1.03 form':>10} {'Δ':>7}")
        for r in con.execute(
            """
            SELECT
                p.player_name, pss.team, pss.minutes,
                COALESCE(mc.n_match, 0) AS n_match,
                pss.rating_per_90,
                pss.shrunk_form,
                pss.shrunk_form_eb
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            LEFT JOIN (
                SELECT player_id, season, team, COUNT(*) AS n_match
                FROM player_match_stats
                WHERE minutes >= 45
                GROUP BY player_id, season, team
            ) mc
              ON mc.player_id = pss.player_id
             AND mc.season = pss.season
             AND mc.team = pss.team
            WHERE pss.season = '2025-2026'
              AND pss.minutes BETWEEN 500 AND 1000
            ORDER BY pss.rating_per_90 DESC
            LIMIT 8
            """
        ).fetchall():
            name, team, mins, nmatch, raw, sf, sf_eb = r
            delta = sf_eb - sf
            print(f"  {name[:26]:<26} {team[:16]:<16} "
                  f"{mins:>5} {nmatch:>5} {raw:>6.3f} "
                  f"{sf:>10.3f} {sf_eb:>10.3f} {delta:>+7.3f}")

        # Distribution stats.
        print(f"\n--- Overall distribution (2025-2026) ---")
        for col, label in [
            ("shrunk_form", "V1.02 form"),
            ("shrunk_form_eb", "V1.03 form"),
            ("shrunk_consistency", "V1.02 consistency"),
            ("shrunk_consistency_eb", "V1.03 consistency"),
        ]:
            r = con.execute(
                f"""
                SELECT AVG({col}), STDDEV({col}), MIN({col}), MAX({col})
                FROM player_season_stats
                WHERE season = '2025-2026'
                """
            ).fetchone()
            print(f"  {label:<22} avg={r[0]:.3f} sd={r[1]:.3f} "
                  f"min={r[2]:.3f} max={r[3]:.3f}")
    finally:
        con.close()


if __name__ == "__main__":
    main()