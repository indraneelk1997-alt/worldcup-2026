"""
V1.02 modeling — STEP 2: compute and populate Bayesian shrunk ratings.

WHAT THIS DOES
    For every row in player_season_stats, compute and write two values:

      shrunk_form        — per-row shrinkage. Uses the row's own (rating, minutes).
                           Captures recent form within a single season.
      shrunk_consistency — career-aggregate shrinkage. Uses the player's
                           minutes-weighted career rating and total minutes
                           across all seasons. Captures stable ability.

    Both columns are filled for every player_season_stats row. Same player
    across two seasons gets DIFFERENT shrunk_form values (one per row) but
    the SAME shrunk_consistency value (assigned from the career aggregate).

THE MATH
    Shrunk = w · observed + (1 - w) · prior
    where w = minutes / (minutes + k), k = 900

    Prior is computed three ways for diagnostic comparison, but only one
    is used to actually shrink (see DECISIONS LOCKED IN below).

DECISIONS LOCKED IN (S6 + S7, see Notion KNOWN_LIMITATIONS task)
    - Prior: Option (iii), minutes-weighted league mean of >=450-min ROWS.
      (Per-row filter, not per-player. A player with 200 min in 24-25 and
      600 min in 25-26 contributes only the 25-26 row to the prior.)
    - k = 900 (heuristic — 10 full matches as the "half-shrunk" point).
    - SAME prior used for both shrunk_form and shrunk_consistency. Prior
      is "what an average player looks like" and doesn't change based on
      whether we're looking at a season or a career.
    - Form-vs-consistency mixing weight (0.75 / 0.25) is a SIMULATOR-side
      decision, not a database-side one. This script does not blend them.

EMPIRICAL FINDING (first run, S7)
    Priors (i) and (ii) came back identical: 0.2428 vs 0.2428. This means
    every row in player_season_stats is already >=450 min — the loader
    applied the filter upstream. So the "filtered vs unfiltered" comparison
    is moot for the current data. We keep the three-prior diagnostic anyway
    because future loaders (e.g. when V1.04 adds more leagues) may not
    pre-filter, and the diagnostic stays useful.

    Prior (iii) was 0.2390 — only 0.0038 below (ii). Minutes-weighting
    barely moves the league mean, which tells us the >=450-min population
    is fairly homogeneous in per-90 vs minutes. The model is not fragile
    to prior choice at this scale.

SEASON STRING FORMAT
    The DB stores seasons as full years: '2024-2025', '2025-2026'.
    NOT the shortened '2024-25' form that appears in some doc strings.
    Sanity-check queries below use the full form.

HOW TO RUN
    From the repo root:
        uv run python src/model/compute_shrinkage.py

    Idempotent: re-running overwrites the shrunk_* columns with the same
    values. Safe to re-run after tuning k or the prior choice.
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# --- locked decisions ------------------------------------------------------
K = 900                # effective minutes of the prior (S7 decision)
MIN_MINUTES_FILTER = 450  # rows below this don't contribute to the prior
CURRENT_SEASON = "2025-2026"  # season used in sanity-check printouts


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # ====================================================================
        # 1. Sanity: confirm the target columns exist (step 1 ran first).
        # ====================================================================
        cols = {
            row[0] for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }
        missing = {"shrunk_form", "shrunk_consistency"} - cols
        if missing:
            raise SystemExit(
                f"Columns {missing} not on player_season_stats. "
                f"Run src/model/add_shrinkage_columns.py first."
            )

        # ====================================================================
        # 2. Compute the three diagnostic priors.
        #    The promise from S6: print (i), (ii), and (iii) so we can sanity-
        #    check that the choice of prior actually matters (or doesn't).
        # ====================================================================
        prior_unweighted_all = con.execute(
            "SELECT AVG(rating_per_90) FROM player_season_stats"
        ).fetchone()[0]

        prior_unweighted_filtered = con.execute(
            "SELECT AVG(rating_per_90) FROM player_season_stats "
            "WHERE minutes >= ?",
            [MIN_MINUTES_FILTER],
        ).fetchone()[0]

        prior_weighted_filtered = con.execute(
            """
            SELECT SUM(rating_per_90 * minutes) * 1.0 / SUM(minutes)
            FROM player_season_stats
            WHERE minutes >= ?
            """,
            [MIN_MINUTES_FILTER],
        ).fetchone()[0]

        print("Diagnostic priors (S6 promise):")
        print(f"  (i)   all players, unweighted mean      : {prior_unweighted_all:.4f}")
        print(f"  (ii)  >=450 min only, unweighted mean   : {prior_unweighted_filtered:.4f}")
        print(f"  (iii) >=450 min, minutes-weighted mean  : {prior_weighted_filtered:.4f}  <-- USED")
        spread = max(prior_unweighted_all, prior_unweighted_filtered,
                     prior_weighted_filtered) - \
                 min(prior_unweighted_all, prior_unweighted_filtered,
                     prior_weighted_filtered)
        print(f"  spread across the three: {spread:.4f}")
        if spread < 0.05:
            print("  -> choice of prior barely matters (spread < 0.05).")
        elif spread > 0.15:
            print("  -> large spread (> 0.15) — selection effects are real.")
        else:
            print("  -> moderate spread — prior choice has some effect.")

        PRIOR = prior_weighted_filtered  # decision locked in S6
        print(f"\nUsing prior = {PRIOR:.4f}, k = {K}")

        # ====================================================================
        # 3. shrunk_form — per-row shrinkage.
        #    Pure SQL update. For each row:
        #      w = minutes / (minutes + K)
        #      shrunk_form = w * rating_per_90 + (1-w) * PRIOR
        #
        #    Done inside a transaction so a failure leaves the table clean.
        # ====================================================================
        print("\nComputing shrunk_form (per-row)...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                """
                UPDATE player_season_stats
                SET shrunk_form =
                    (minutes * 1.0 / (minutes + ?)) * rating_per_90
                  + (? * 1.0 / (minutes + ?)) * ?
                """,
                [K, K, K, PRIOR],
            )

            # ================================================================
            # 4. shrunk_consistency — career-aggregate shrinkage.
            #    For each player:
            #      career_minutes = SUM(minutes across all rows)
            #      career_rating  = SUM(rating_per_90 * minutes) / career_minutes
            #      w              = career_minutes / (career_minutes + K)
            #      shrunk_consist = w * career_rating + (1-w) * PRIOR
            #    Then write that single value back onto EVERY row for that player.
            # ================================================================
            print("Computing shrunk_consistency (career-aggregate)...")

            # 4a. Build a per-player aggregate (CTE-style temp result).
            per_player = con.execute(
                """
                SELECT
                    player_id,
                    SUM(minutes) AS career_minutes,
                    SUM(rating_per_90 * minutes) * 1.0 / SUM(minutes)
                        AS career_rating
                FROM player_season_stats
                GROUP BY player_id
                """
            ).fetchall()

            # 4b. Shrink each player's career rating once, hold in a dict.
            shrunk_by_player = {}
            for player_id, career_minutes, career_rating in per_player:
                w = career_minutes / (career_minutes + K)
                shrunk_by_player[player_id] = (
                    w * career_rating + (1 - w) * PRIOR
                )

            # 4c. Write back. UPDATE one player at a time; small table
            # (~270 players), no need for fancy bulk write.
            for player_id, shrunk_val in shrunk_by_player.items():
                con.execute(
                    "UPDATE player_season_stats SET shrunk_consistency = ? "
                    "WHERE player_id = ?",
                    [shrunk_val, player_id],
                )

            # ================================================================
            # 5. Verify — every row should have non-NULL values in both
            # shrunk columns. If any are NULL we have a bug.
            # ================================================================
            null_form = con.execute(
                "SELECT COUNT(*) FROM player_season_stats "
                "WHERE shrunk_form IS NULL"
            ).fetchone()[0]
            null_consistency = con.execute(
                "SELECT COUNT(*) FROM player_season_stats "
                "WHERE shrunk_consistency IS NULL"
            ).fetchone()[0]
            if null_form or null_consistency:
                raise SystemExit(
                    f"NULL values found after compute: "
                    f"shrunk_form={null_form}, shrunk_consistency={null_consistency}. "
                    f"Investigate before committing."
                )

            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during compute, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # ====================================================================
        # 6. Sanity checks — show the rank changes shrinkage made.
        #    This is where Zirkzee should fall, and high-minutes players
        #    should stay roughly where they were.
        # ====================================================================
        print(f"\n--- TOP 10 by raw rating_per_90 ({CURRENT_SEASON}, EPL only) ---")
        rows = con.execute(
            f"""
            SELECT p.player_name, pss.team, pss.minutes,
                   pss.rating_per_90, pss.shrunk_form
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '{CURRENT_SEASON}'
            ORDER BY pss.rating_per_90 DESC
            LIMIT 10
            """
        ).fetchall()
        print(f"{'player':<28} {'team':<14} {'min':>5} "
              f"{'raw':>6} {'shrunk':>7}")
        for name, team, minutes, raw, shrunk in rows:
            print(f"{name[:28]:<28} {team[:14]:<14} {minutes:>5} "
                  f"{raw:>6.3f} {shrunk:>7.3f}")

        print(f"\n--- TOP 10 by shrunk_form ({CURRENT_SEASON}, EPL only) ---")
        rows = con.execute(
            f"""
            SELECT p.player_name, pss.team, pss.minutes,
                   pss.rating_per_90, pss.shrunk_form
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '{CURRENT_SEASON}'
            ORDER BY pss.shrunk_form DESC
            LIMIT 10
            """
        ).fetchall()
        print(f"{'player':<28} {'team':<14} {'min':>5} "
              f"{'raw':>6} {'shrunk':>7}")
        for name, team, minutes, raw, shrunk in rows:
            print(f"{name[:28]:<28} {team[:14]:<14} {minutes:>5} "
                  f"{raw:>6.3f} {shrunk:>7.3f}")

        print("\n--- TOP 10 by shrunk_consistency (career, EPL only) ---")
        rows = con.execute(
            """
            SELECT p.player_name,
                   ANY_VALUE(pss.team) AS recent_team,
                   SUM(pss.minutes) AS career_min,
                   pss.shrunk_consistency
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            GROUP BY p.player_name, pss.shrunk_consistency
            ORDER BY pss.shrunk_consistency DESC
            LIMIT 10
            """
        ).fetchall()
        print(f"{'player':<28} {'team':<14} {'min':>6} {'shrunk':>7}")
        for name, team, career_min, shrunk in rows:
            print(f"{name[:28]:<28} {team[:14]:<14} {career_min:>6} {shrunk:>7.3f}")

        # 6d. The form-vs-consistency divergence list. These are exactly the
        # players where the form/consistency call matters — useful diagnostic.
        print(f"\n--- Biggest form-vs-consistency gaps ({CURRENT_SEASON}, EPL, abs diff) ---")
        rows = con.execute(
            f"""
            SELECT p.player_name, pss.team, pss.minutes,
                   pss.shrunk_form, pss.shrunk_consistency,
                   pss.shrunk_form - pss.shrunk_consistency AS gap
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '{CURRENT_SEASON}'
            ORDER BY ABS(pss.shrunk_form - pss.shrunk_consistency) DESC
            LIMIT 10
            """
        ).fetchall()
        print(f"{'player':<28} {'team':<14} {'min':>5} "
              f"{'form':>6} {'consis':>7} {'gap':>7}")
        for name, team, minutes, form, consist, gap in rows:
            print(f"{name[:28]:<28} {team[:14]:<14} {minutes:>5} "
                  f"{form:>6.3f} {consist:>7.3f} {gap:>+7.3f}")
    finally:
        con.close()


if __name__ == "__main__":
    main()