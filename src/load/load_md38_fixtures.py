"""
V1.02 modeling — STEP 6a: load MD38 fixtures + normalize season strings.

WHAT THIS DOES
    Two things, both touching the `fixtures` table:
      1. Loads data/fixtures/epl_2025-2026_matchday_38.csv into `fixtures`.
         10 EPL matchday 38 rows. Idempotency-guarded (uses INSERT OR IGNORE).
      2. Normalizes the trial fixture's season string from '2024-25' to
         '2024-2025' to match the convention used by player_season_stats.

WHY BOTH IN ONE SCRIPT
    Same target table, same goal (prepare fixtures for V1.02 prediction
    run). The season-string fix is small but blocks downstream joins; the
    fixture load is the actual data we need. Keeping them together avoids
    "did I run both pre-steps?" doubt.

NOTES ON THE CSV
    Discovered in S8 (was loaded as a CSV but never into DuckDB).
    Format:
      fixture_id,season,match_date,home_team,away_team,matchday
      2025-26_md38_bri_mun,2025-2026,2026-05-24,Brighton,Manchester United,38
      ...

    fixture_id uses short-form season prefix ('2025-26_'). We leave this
    as-is — fixture_id is opaque; what matters is the `season` column
    (full form, '2025-2026'). Mixed conventions within the file are
    documented but not a blocker.

TEAM NAME COMPATIBILITY
    Verify that team names in the CSV match what's in player_season_stats
    EXACTLY before declaring success. Mismatches (e.g. "Man Utd" vs
    "Manchester United") would break downstream best_xi lookups.

HOW TO RUN
    From the repo root:
        uv run python src/load/load_md38_fixtures.py
"""

import csv
import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")
CSV_PATH = Path("data/fixtures/epl_2025-2026_matchday_38.csv")

# Trial fixture details for the season normalization step.
TRIAL_FIXTURE_ID = "2024-25_ars_liv_trial"
OLD_SEASON = "2024-25"
NEW_SEASON = "2024-2025"


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )
    if not CSV_PATH.exists():
        raise SystemExit(
            f"MD38 fixtures CSV not found at {CSV_PATH}."
        )

    # 1. Read the CSV.
    rows = []
    with open(CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append((
                r["fixture_id"],
                r["season"],
                r["match_date"],
                r["home_team"],
                r["away_team"],
                int(r["matchday"]),
            ))
    print(f"Read {len(rows)} fixtures from CSV.")
    if len(rows) != 10:
        print(f"  WARNING: expected 10 MD38 fixtures, got {len(rows)}.")

    # 2. Connect to DB and verify team-name compatibility BEFORE writing.
    con = duckdb.connect(str(DB_PATH))
    try:
        # Set of teams the model can actually rate.
        db_teams = {
            r[0] for r in con.execute(
                "SELECT DISTINCT team FROM player_season_stats "
                "WHERE season = '2025-2026'"
            ).fetchall()
        }
        # Teams referenced in the CSV.
        csv_teams = set()
        for _, _, _, home, away, _ in rows:
            csv_teams.add(home)
            csv_teams.add(away)

        missing = csv_teams - db_teams
        if missing:
            print(f"\n!!! Team name mismatch — CSV references teams "
                  f"not in player_season_stats:")
            for t in sorted(missing):
                print(f"  '{t}'")
            print(f"\nCheck for case/spelling differences. Aborting.")
            return
        print(f"  All {len(csv_teams)} teams in CSV match "
              f"player_season_stats.")

        # 3. Apply changes in a transaction.
        print("\nBeginning transaction...")
        con.execute("BEGIN TRANSACTION")
        try:
            # 3a. Normalize the trial fixture's season.
            res = con.execute(
                "SELECT COUNT(*) FROM fixtures WHERE season = ?",
                [OLD_SEASON],
            ).fetchone()
            if res[0] > 0:
                print(f"  Updating trial fixture: season "
                      f"'{OLD_SEASON}' -> '{NEW_SEASON}'")
                con.execute(
                    "UPDATE fixtures SET season = ? WHERE season = ?",
                    [NEW_SEASON, OLD_SEASON],
                )
            else:
                print(f"  No fixtures with season='{OLD_SEASON}' "
                      f"(already normalized — skipping).")

            # 3b. Load MD38 fixtures.
            # Use INSERT OR IGNORE in case the script's run before.
            con.executemany(
                """
                INSERT OR IGNORE INTO fixtures
                    (fixture_id, season, match_date, home_team,
                     away_team, matchday)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

            # 3c. Verify.
            total = con.execute(
                "SELECT COUNT(*) FROM fixtures"
            ).fetchone()[0]
            md38_count = con.execute(
                "SELECT COUNT(*) FROM fixtures WHERE matchday = 38"
            ).fetchone()[0]
            print(f"  Total fixtures: {total}")
            print(f"  MD38 fixtures:  {md38_count}")

            if md38_count != 10:
                raise SystemExit(
                    f"Expected 10 MD38 fixtures, found {md38_count}. "
                    f"Rolling back."
                )

            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            print("!!! Error during writes, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 4. Display all fixtures.
        print("\n--- All fixtures in DB ---")
        rows_out = con.execute(
            """
            SELECT fixture_id, season, match_date, home_team,
                   away_team, matchday
            FROM fixtures
            ORDER BY match_date, fixture_id
            """
        ).fetchall()
        for r in rows_out:
            md_str = f"MD{r[5]}" if r[5] is not None else "(no MD)"
            print(f"  {r[0]:<28} {r[1]:<10} {str(r[2]):<12} "
                  f"{r[3]:<16} vs {r[4]:<26} {md_str}")
    finally:
        con.close()


if __name__ == "__main__":
    main()