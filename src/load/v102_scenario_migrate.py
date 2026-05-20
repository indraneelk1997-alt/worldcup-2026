"""
V1.02 schema refactor — PART 2 of 2: rebind fixture_lineups + predictions.

WHAT THIS DOES (DESTRUCTIVE — but transactional)
    1. Patches scenario_teams: drops the NOT NULL on formation, so legacy
       rows (V1.01 trial data, no real formation) can carry NULL honestly.
       The part-1 script has also been updated so re-running it on a fresh
       DB produces the same shape — this ALTER is for the existing DB.
    2. Snapshots the 22 fixture_lineups rows and 1 predictions row into
       Python memory before any DROP. Belt-and-braces: DuckDB transactions
       roll back on failure, but a Python-side copy is one more layer.
    3. Drops the old fixture_lineups and predictions tables (children of
       fixtures via fixture_id FK).
    4. Recreates them with the new shape:
         fixture_lineups: (scenario_id, side, slot_no, player_id) — PK is
           (scenario_id, side, slot_no), with FKs to lineup_scenarios,
           scenario_teams, and players. No `team` (now on scenario_teams)
           and no `is_starter` (starters-only schema for V1.02; subs in V1.03).
         predictions: same 17 metric columns as before; the only change is
           fixture_id VARCHAR -> scenario_id INTEGER REFERENCES lineup_scenarios.
    5. Inserts the trial data into the new schema:
         - 1 row in lineup_scenarios (scenario_id=1, scenario_type='legacy_v1.01')
         - 2 rows in scenario_teams (home/away, formation=NULL)
         - 22 rows in fixture_lineups, slot_no 1..11 per side ordered by
           player_id ASC (no real slot info in the source — arbitrary but stable)
         - 1 row in predictions with scenario_id=1

EVERYTHING IS WRAPPED IN A SINGLE TRANSACTION. If any step fails, the whole
migration rolls back and the DB is unchanged. See DuckDB transactions doc:
https://duckdb.org/docs/stable/sql/statements/transactions

HOW TO RUN
    From the repo root:
        uv run python src/load/v102_scenario_migrate.py

NOT IDEMPOTENT. This script is a one-shot. If the legacy rows are already
migrated (lineup_scenarios row exists for the trial fixture), it will refuse
to run rather than duplicate or corrupt.
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")
TRIAL_FIXTURE_ID = "2024-25_ars_liv_trial"


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # === 0. Idempotency guard ===========================================
        # If a scenario already exists for the trial fixture, the migration
        # has already run. Refuse rather than corrupt.
        existing = con.execute(
            "SELECT scenario_id FROM lineup_scenarios WHERE fixture_id = ?",
            [TRIAL_FIXTURE_ID],
        ).fetchall()
        if existing:
            raise SystemExit(
                f"Refusing to run: lineup_scenarios already has a row for "
                f"fixture_id='{TRIAL_FIXTURE_ID}' (scenario_id="
                f"{existing[0][0]}). Migration appears to have already run."
            )

        # === 1. Snapshot trial data BEFORE any destructive op ==============
        # Read everything we need into Python memory. If something goes wrong
        # mid-migration, we have these for re-insertion (and the transaction
        # rolls back anyway).
        print("Snapshotting trial data...")

        # 1a. Fixtures row — to know which team is home vs away.
        fixture_row = con.execute(
            "SELECT fixture_id, home_team, away_team FROM fixtures WHERE fixture_id = ?",
            [TRIAL_FIXTURE_ID],
        ).fetchone()
        if fixture_row is None:
            raise SystemExit(
                f"No row in fixtures with fixture_id='{TRIAL_FIXTURE_ID}'. "
                f"Cannot determine home/away sides for the trial lineup."
            )
        _, home_team, away_team = fixture_row
        print(f"  Trial fixture: {home_team} (home) vs {away_team} (away)")

        # 1b. fixture_lineups rows.
        lineup_rows = con.execute(
            "SELECT fixture_id, team, player_id, is_starter "
            "FROM fixture_lineups WHERE fixture_id = ?",
            [TRIAL_FIXTURE_ID],
        ).fetchall()
        print(f"  fixture_lineups: {len(lineup_rows)} rows")
        if len(lineup_rows) != 22:
            raise SystemExit(
                f"Expected 22 fixture_lineups rows for the trial, got {len(lineup_rows)}."
            )

        # 1c. predictions rows. Save column order so we can re-insert cleanly.
        prediction_cols = [
            "prediction_id", "fixture_id", "model_version", "run_timestamp",
            "n_simulations", "rng_seed", "base_goals", "k_param",
            "home_strength", "away_strength", "xg_home", "xg_away",
            "p_home_win", "p_draw", "p_away_win",
            "avg_home_goals", "avg_away_goals", "modal_scoreline",
        ]
        prediction_rows = con.execute(
            f"SELECT {', '.join(prediction_cols)} FROM predictions WHERE fixture_id = ?",
            [TRIAL_FIXTURE_ID],
        ).fetchall()
        print(f"  predictions:    {len(prediction_rows)} rows")
        if len(prediction_rows) != 1:
            raise SystemExit(
                f"Expected 1 predictions row for the trial, got {len(prediction_rows)}."
            )

        # 1d. Check there are no OTHER fixture_ids hiding in either table.
        # If there are, this script can't migrate them honestly — they'd need
        # their own scenarios. Fail loudly rather than drop them silently.
        other_lineups = con.execute(
            "SELECT DISTINCT fixture_id FROM fixture_lineups WHERE fixture_id != ?",
            [TRIAL_FIXTURE_ID],
        ).fetchall()
        other_preds = con.execute(
            "SELECT DISTINCT fixture_id FROM predictions WHERE fixture_id != ?",
            [TRIAL_FIXTURE_ID],
        ).fetchall()
        if other_lineups or other_preds:
            raise SystemExit(
                f"Other fixture_ids found in tables, migration is single-fixture only.\n"
                f"  fixture_lineups: {other_lineups}\n"
                f"  predictions:     {other_preds}"
            )

        # === 2. Begin the destructive work, wrapped in a transaction ========
        print("\nBeginning transaction...")
        con.execute("BEGIN TRANSACTION")

        try:
            # 2a. Patch scenario_teams: formation -> nullable.
            print("  ALTER scenario_teams: formation NOT NULL -> nullable")
            con.execute("ALTER TABLE scenario_teams ALTER COLUMN formation DROP NOT NULL")

            # 2b. Drop the old tables. Order: children before parents.
            # predictions and fixture_lineups are both children of fixtures
            # (FK on fixture_id). Neither references the other.
            print("  DROP TABLE predictions")
            con.execute("DROP TABLE predictions")
            print("  DROP TABLE fixture_lineups")
            con.execute("DROP TABLE fixture_lineups")

            # 2c. Create the new fixture_lineups.
            # PK (scenario_id, side, slot_no) -> one player per slot.
            # FK (scenario_id, side) -> scenario_teams -> ties the lineup to a
            # specific team + formation. No `team` column (redundant) and no
            # `is_starter` column (starters-only schema; subs are V1.03).
            print("  CREATE TABLE fixture_lineups (new shape)")
            con.execute("""
                CREATE TABLE fixture_lineups (
                    scenario_id INTEGER NOT NULL REFERENCES lineup_scenarios(scenario_id),
                    side        VARCHAR NOT NULL CHECK (side IN ('home','away')),
                    slot_no     INTEGER NOT NULL CHECK (slot_no BETWEEN 1 AND 11),
                    player_id   INTEGER NOT NULL REFERENCES players(player_id),
                    PRIMARY KEY (scenario_id, side, slot_no),
                    FOREIGN KEY (scenario_id, side) REFERENCES scenario_teams(scenario_id, side)
                )
            """)

            # 2d. Create the new predictions table.
            # Only change from old shape: fixture_id VARCHAR -> scenario_id INTEGER FK.
            # All 17 other columns preserved exactly.
            print("  CREATE TABLE predictions (new shape)")
            con.execute("""
                CREATE TABLE predictions (
                    prediction_id   VARCHAR PRIMARY KEY,
                    scenario_id     INTEGER NOT NULL REFERENCES lineup_scenarios(scenario_id),
                    model_version   VARCHAR NOT NULL,
                    run_timestamp   TIMESTAMP NOT NULL,
                    n_simulations   INTEGER NOT NULL,
                    rng_seed        INTEGER NOT NULL,
                    base_goals      DOUBLE NOT NULL,
                    k_param         DOUBLE NOT NULL,
                    home_strength   DOUBLE NOT NULL,
                    away_strength   DOUBLE NOT NULL,
                    xg_home         DOUBLE NOT NULL,
                    xg_away         DOUBLE NOT NULL,
                    p_home_win      DOUBLE NOT NULL,
                    p_draw          DOUBLE NOT NULL,
                    p_away_win      DOUBLE NOT NULL,
                    avg_home_goals  DOUBLE NOT NULL,
                    avg_away_goals  DOUBLE NOT NULL,
                    modal_scoreline VARCHAR NOT NULL
                )
            """)

            # 2e. Insert the legacy scenario row. scenario_id=1 hardcoded —
            # there are no other scenarios in the table (we'd have failed at
            # step 0 if there were).
            print("  INSERT lineup_scenarios (1 row, scenario_id=1, legacy_v1.01)")
            con.execute("""
                INSERT INTO lineup_scenarios
                    (scenario_id, fixture_id, scenario_type, label)
                VALUES (?, ?, ?, ?)
            """, [
                1,
                TRIAL_FIXTURE_ID,
                "legacy_v1.01",
                "ARS vs LIV trial (V1.01 baseline, pre-formation)",
            ])

            # 2f. Insert the two team rows. formation=NULL (legacy data).
            print(f"  INSERT scenario_teams (2 rows: {home_team} home, {away_team} away)")
            con.executemany("""
                INSERT INTO scenario_teams
                    (scenario_id, side, team, formation)
                VALUES (?, ?, ?, ?)
            """, [
                (1, "home", home_team, None),
                (1, "away", away_team, None),
            ])

            # 2g. Insert the 22 lineup rows. Group by team, then assign
            # slot_no 1..11 per side ordered by player_id ASC. Stable but
            # arbitrary — no real position info in V1.01 trial data.
            print("  INSERT fixture_lineups (22 rows, slot_no by player_id ASC)")
            home_players = sorted(
                [r[2] for r in lineup_rows if r[1] == home_team]
            )
            away_players = sorted(
                [r[2] for r in lineup_rows if r[1] == away_team]
            )
            if len(home_players) != 11 or len(away_players) != 11:
                raise SystemExit(
                    f"Expected 11 home and 11 away players, got "
                    f"{len(home_players)} home + {len(away_players)} away. "
                    f"Team name mismatch with fixtures table?"
                )
            new_lineup_rows = []
            for slot_no, pid in enumerate(home_players, start=1):
                new_lineup_rows.append((1, "home", slot_no, pid))
            for slot_no, pid in enumerate(away_players, start=1):
                new_lineup_rows.append((1, "away", slot_no, pid))
            con.executemany("""
                INSERT INTO fixture_lineups
                    (scenario_id, side, slot_no, player_id)
                VALUES (?, ?, ?, ?)
            """, new_lineup_rows)

            # 2h. Insert the prediction row with scenario_id swapped in for
            # fixture_id. All other columns preserved verbatim from snapshot.
            print("  INSERT predictions (1 row, scenario_id=1)")
            old = prediction_rows[0]
            # old tuple order is prediction_cols; we replace index 1 (fixture_id)
            # with scenario_id and keep the rest.
            new_pred_row = (
                old[0],                  # prediction_id
                1,                       # scenario_id (was fixture_id)
                *old[2:],                # remaining 16 cols verbatim
            )
            con.execute("""
                INSERT INTO predictions
                    (prediction_id, scenario_id, model_version, run_timestamp,
                     n_simulations, rng_seed, base_goals, k_param,
                     home_strength, away_strength, xg_home, xg_away,
                     p_home_win, p_draw, p_away_win,
                     avg_home_goals, avg_away_goals, modal_scoreline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, list(new_pred_row))

            # 2i. Verify row counts before committing. If any are wrong, raise
            # so the outer except rolls back.
            print("\nVerifying...")
            checks = {
                "lineup_scenarios": 1,
                "scenario_teams":   2,
                "fixture_lineups": 22,
                "predictions":      1,
            }
            for tbl, expected in checks.items():
                n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                ok = "OK" if n == expected else "FAIL"
                print(f"  {tbl:<18} {n:>4} (expected {expected}) [{ok}]")
                if n != expected:
                    raise SystemExit(
                        f"Row count mismatch: {tbl} has {n}, expected {expected}"
                    )

            # 2j. Sample check the FK relationships actually resolve.
            sample = con.execute("""
                SELECT s.scenario_id, s.scenario_type, st.side, st.team,
                       st.formation, COUNT(fl.player_id) AS n_players
                FROM lineup_scenarios s
                JOIN scenario_teams st USING (scenario_id)
                JOIN fixture_lineups fl USING (scenario_id, side)
                GROUP BY s.scenario_id, s.scenario_type, st.side, st.team, st.formation
                ORDER BY st.side
            """).fetchall()
            print("\nFK round-trip check (scenario -> team -> lineup):")
            for row in sample:
                print(f"  {row}")

            # 2k. Commit.
            con.execute("COMMIT")
            print("\nCOMMITTED. Migration complete.")

        except Exception:
            print("\n!!! Error during migration, rolling back !!!")
            con.execute("ROLLBACK")
            raise

    finally:
        con.close()


if __name__ == "__main__":
    main()