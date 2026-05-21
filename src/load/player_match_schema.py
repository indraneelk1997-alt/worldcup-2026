"""
V1.03 modeling — STEP 1a: schema for per-match player data.

WHAT THIS DOES
    Creates two new tables that hold per-match data from Understat:

    1. games — one row per match
        (game_id, season, match_date, home_team, away_team)

    2. player_match_stats — one row per (player, match)
        ~22K rows for both 2024-2025 and 2025-2026 EPL seasons.
        Carries the rich Understat per-match payload: minutes, goals,
        shots, xg, xg_chain, xg_buildup, assists, xa, key_passes,
        cards, plus position + position_id (16-code vocabulary finer
        than season-level D/M/F/GK).

SCHEMA DECISIONS (S10 lock)
    - games is a separate table (not denormalized onto player_match_stats)
      so future per-team-match data (A2) can also reference it.
    - player_match_stats has BOTH `position` (raw Understat code, may be
      'Sub') and `effective_position` (backfilled for Sub rows from
      player's most-common other-match position). Preserves source-of-
      truth while making downstream code easy.
    - Foreign keys: game_id → games, player_id → players. The backfill
      script (next file) pre-populates `players` so all player_ids exist
      before this table is loaded.
    - Idempotency: schema creation is CREATE IF NOT EXISTS. The backfill
      script wipes by season before re-inserting.

POSITION VOCABULARY (Understat per-match)
    16 distinct codes observed in S10 recon (plus 'Sub'):
      GK, DC, DL, DR, DML, DMR, DMC, MC, ML, MR, AMC, AML, AMR,
      FW, FWL, FWR, Sub.
    These are FINER than season-level codes (D/M/F/GK/S) and let us
    distinguish wing-backs (DML/DMR) from full-backs (DL/DR), and
    DMs (DMC) from CMs (MC) from CAMs (AMC). Big V1.03 unlock.

HOW TO RUN
    From the repo root:
        uv run python src/load/player_match_schema.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }

        both_exist = (
            "games" in existing and "player_match_stats" in existing
        )
        if both_exist:
            print("Both `games` and `player_match_stats` already exist.")
            print("Nothing to do. (Re-run is safe.)")
            return

        print("Creating per-match tables...")
        con.execute("BEGIN TRANSACTION")
        try:
            # 1. games — match metadata, referenced by player_match_stats
            # AND eventually by team_match_stats (A2).
            if "games" not in existing:
                con.execute("""
                    CREATE TABLE games (
                        game_id     INTEGER PRIMARY KEY,
                        season      VARCHAR NOT NULL,
                        match_date  DATE NOT NULL,
                        home_team   VARCHAR NOT NULL,
                        away_team   VARCHAR NOT NULL
                    )
                """)
                print("  Created `games`.")

            # 2. player_match_stats — the main payload.
            if "player_match_stats" not in existing:
                con.execute("""
                    CREATE TABLE player_match_stats (
                        game_id            INTEGER NOT NULL REFERENCES games(game_id),
                        player_id          INTEGER NOT NULL REFERENCES players(player_id),
                        season             VARCHAR NOT NULL,
                        team               VARCHAR NOT NULL,
                        position           VARCHAR NOT NULL,
                        effective_position VARCHAR NOT NULL,
                        position_id        INTEGER NOT NULL,
                        minutes            INTEGER NOT NULL,
                        goals              INTEGER NOT NULL,
                        own_goals          INTEGER NOT NULL,
                        shots              INTEGER NOT NULL,
                        xg                 DOUBLE  NOT NULL,
                        xg_chain           DOUBLE  NOT NULL,
                        xg_buildup         DOUBLE  NOT NULL,
                        assists            INTEGER NOT NULL,
                        xa                 DOUBLE  NOT NULL,
                        key_passes         INTEGER NOT NULL,
                        yellow_cards       INTEGER NOT NULL,
                        red_cards          INTEGER NOT NULL,
                        PRIMARY KEY (game_id, player_id)
                    )
                """)
                print("  Created `player_match_stats`.")

            con.execute("COMMIT")
            print("COMMITTED.")
        except Exception:
            print("!!! Error during CREATE, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # Verify columns.
        for table in ("games", "player_match_stats"):
            print(f"\n{table} columns:")
            rows = con.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = ?
                ORDER BY ordinal_position
                """,
                [table],
            ).fetchall()
            for col_name, dtype, nullable in rows:
                print(f"  {col_name:<20} {dtype:<10} nullable={nullable}")
    finally:
        con.close()


if __name__ == "__main__":
    main()