"""
V1.03 modeling — STEP 1b: backfill games + player_match_stats.

WHAT THIS DOES
    Pulls per-match player stats from Understat (via cached soccerdata),
    transforms, and loads into the new V1.03 tables:
      1. Adds any new players to `players` (sub-450-min players may
         appear in per-match data but not in our season-aggregate set).
      2. Populates `games` from the per-match data's game metadata.
      3. Populates `player_match_stats` for both 2024-2025 and 2025-2026
         seasons.
      4. Computes `effective_position` per row using the policy-C
         3-step fallback chain (see below).

POLICY-C: EFFECTIVE POSITION FOR SUB ROWS
    'Sub' position rows (6,245 / 22,745 = 27% of data) get a
    backfilled `effective_position` value via this fallback chain:
      1. The player's MOST COMMON non-Sub position across all their
         per-match rows in this dataset. Counted by row count.
      2. If a player has ONLY Sub appearances: map from their
         `player_season_stats.position_class`:
             GK  -> 'GK'
             DEF -> 'DC'
             MID -> 'MC'
             FWD -> 'FW'
      3. If still nothing (player not in player_season_stats and has
         only Sub rows): keep `effective_position = 'Sub'` and log.
    For non-Sub rows: `effective_position = position` (trivial passthrough).

SEASON STRING NORMALIZATION
    Understat's per-match returns '2425'/'2526'; our DB uses
    '2024-2025'/'2025-2026'. Same mapping as backfill_player_positions.py.

IDEMPOTENCY
    Wipes `player_match_stats` and `games` by season then re-inserts.
    `players` augmentation uses INSERT OR IGNORE.

HOW TO RUN
    From the repo root:
        uv run python src/load/backfill_player_match.py
"""

import duckdb
import soccerdata as sd
import pandas as pd
from collections import Counter
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

SEASON_MAP = {
    "2024-2025": "2425",
    "2025-2026": "2526",
}

# Fallback step 2: class -> default per-match position code.
CLASS_TO_POSITION = {
    "GK":  "GK",
    "DEF": "DC",
    "MID": "MC",
    "FWD": "FW",
}


def parse_game_string(game_str):
    """
    Understat's per-match index has a `game` field like
    '2025-08-15 Liverpool-Bournemouth'. Parse out the date.
    Returns a python date or None.
    """
    try:
        date_part = game_str.split(" ", 1)[0]
        return pd.to_datetime(date_part).date()
    except Exception:
        return None


def compute_effective_position(df, season_stats_class_lookup):
    """
    Returns a dict {(game_id, player_id) -> effective_position_str}.

    Applies the policy-C 3-step fallback:
      1. Non-Sub rows: trivial passthrough.
      2. Sub rows: try the player's most-common non-Sub position
         from this dataset.
      3. Players with ONLY Sub rows: try mapping from their
         player_season_stats.position_class.
      4. Else: keep 'Sub'.
    """
    # Build a player_id -> Counter of non-Sub positions across all rows.
    non_sub = df[df["position"] != "Sub"]
    player_pos_counter = {}
    for pid, pos in zip(non_sub["player_id"], non_sub["position"]):
        player_pos_counter.setdefault(int(pid), Counter())[pos] += 1

    # Compute primary (most common) non-Sub position per player.
    player_primary = {}
    for pid, ctr in player_pos_counter.items():
        player_primary[pid] = ctr.most_common(1)[0][0]

    # Walk the full df and assign effective_position.
    eff_lookup = {}
    sub_only_count = 0
    fallback_to_class_count = 0
    fallback_to_sub_count = 0
    for game_id, pid, pos in zip(
        df["game_id"], df["player_id"], df["position"]
    ):
        key = (int(game_id), int(pid))
        if pos != "Sub":
            eff_lookup[key] = pos
            continue
        # Step 2: try player's own primary non-Sub position
        primary = player_primary.get(int(pid))
        if primary is not None:
            eff_lookup[key] = primary
            continue
        sub_only_count += 1
        # Step 3: try season_stats class mapping
        # season_stats_class_lookup keyed by player_id alone (player's
        # primary class is stable per player season).
        season_class = season_stats_class_lookup.get(int(pid))
        if season_class is not None:
            mapped = CLASS_TO_POSITION.get(season_class)
            if mapped is not None:
                eff_lookup[key] = mapped
                fallback_to_class_count += 1
                continue
        # Step 4: keep as Sub
        eff_lookup[key] = "Sub"
        fallback_to_sub_count += 1

    print(f"  Sub-only players (no non-Sub rows in this dataset): "
          f"{sub_only_count} rows affected")
    print(f"    of which backfilled from season_stats class: "
          f"{fallback_to_class_count}")
    print(f"    of which kept as 'Sub' (no class either): "
          f"{fallback_to_sub_count}")
    return eff_lookup


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # 1. Pull per-match data from Understat.
    print("Loading Understat per-match stats (uses local cache)...")
    us = sd.Understat(
        leagues="ENG-Premier League",
        seasons=list(SEASON_MAP.keys()),
    )
    df = us.read_player_match_stats().reset_index()
    print(f"  Loaded {len(df)} raw rows.")

    # 2. Normalize season string from '2526' -> '2025-2026'.
    sd_to_db_season = {sd_form: db_form
                       for db_form, sd_form in SEASON_MAP.items()}
    sd_to_db_season.update({db: db for db in SEASON_MAP})  # passthrough
    df["season_db"] = df["season"].astype(str).map(sd_to_db_season)
    if df["season_db"].isna().any():
        bad_seasons = df.loc[df["season_db"].isna(), "season"].unique()
        raise SystemExit(
            f"Unmapped seasons in data: {bad_seasons}. Update SEASON_MAP."
        )

    # 3. Parse match dates from the `game` index field.
    df["match_date"] = df["game"].apply(parse_game_string)
    if df["match_date"].isna().any():
        bad = df.loc[df["match_date"].isna(), "game"].iloc[0]
        raise SystemExit(
            f"Could not parse a date from game string: '{bad}'."
        )

    # 4. Connect to DB. Verify required prior tables.
    con = duckdb.connect(str(DB_PATH))
    try:
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for required in ("games", "player_match_stats", "players",
                         "player_season_stats"):
            if required not in existing:
                raise SystemExit(
                    f"Required table '{required}' missing. Run schema "
                    f"scripts first (V1.01/V1.02 + this version's "
                    f"player_match_schema.py)."
                )

        # 5. Load player_season_stats class lookup (player_id -> class).
        # Used for the policy-C step 3 fallback. A player may have
        # multiple season rows; we just need any class — they're
        # stable per player (a forward is a forward across seasons,
        # roughly).
        season_class_lookup = {
            r[0]: r[1] for r in con.execute(
                "SELECT player_id, position_class FROM player_season_stats"
            ).fetchall()
        }
        print(f"  Loaded {len(season_class_lookup)} season-class "
              f"lookups for fallback.")

        # 6. Compute effective_position with the policy-C chain.
        print("\nComputing effective_position (policy C, 3-step chain)...")
        eff_lookup = compute_effective_position(df, season_class_lookup)

        # 7. Build the games-table rows and player_match_stats-table
        # rows in memory. games is keyed by game_id; player_match_stats
        # is keyed by (game_id, player_id).
        # Players present in per-match data but not in `players` need
        # to be inserted into `players` first.
        existing_player_ids = {
            r[0] for r in con.execute(
                "SELECT player_id FROM players"
            ).fetchall()
        }
        # Get player names from Understat per-match (the `player` field
        # is in the index, we'll use it). Build a (player_id -> name)
        # mapping for any new players to insert.
        new_players_to_insert = []
        seen_new_pids = set()
        for pid, pname in zip(df["player_id"], df["player"]):
            pid_int = int(pid)
            if pid_int in existing_player_ids:
                continue
            if pid_int in seen_new_pids:
                continue
            seen_new_pids.add(pid_int)
            new_players_to_insert.append((pid_int, str(pname)))
        print(f"\n  New players to insert (sub-450-min in season data): "
              f"{len(new_players_to_insert)}")

        # 8. Build the games rows: one row per distinct game_id.
        # We pick the home_team and away_team from the game string,
        # which is formatted as 'YYYY-MM-DD HomeTeam-AwayTeam'.
        # (Recon confirmed Liverpool-Bournemouth was home-away.)
        games_seen = {}
        for game_id, season_db, match_date, game_str in zip(
            df["game_id"], df["season_db"], df["match_date"], df["game"]
        ):
            gid = int(game_id)
            if gid in games_seen:
                continue
            # Parse 'YYYY-MM-DD Home-Away'
            try:
                _, teams_part = game_str.split(" ", 1)
                home_team, away_team = teams_part.split("-", 1)
            except Exception:
                raise SystemExit(
                    f"Could not parse home/away from game string: "
                    f"'{game_str}'"
                )
            games_seen[gid] = (
                gid, season_db, match_date, home_team, away_team
            )
        games_rows = list(games_seen.values())
        print(f"  Games to insert: {len(games_rows)}")

        # 9. Build player_match_stats rows.
        pms_rows = []
        for row in df.itertuples(index=False):
            gid = int(row.game_id)
            pid = int(row.player_id)
            eff_pos = eff_lookup[(gid, pid)]
            pms_rows.append((
                gid, pid, row.season_db, str(row.team),
                str(row.position), eff_pos, int(row.position_id),
                int(row.minutes), int(row.goals), int(row.own_goals),
                int(row.shots), float(row.xg), float(row.xg_chain),
                float(row.xg_buildup), int(row.assists), float(row.xa),
                int(row.key_passes), int(row.yellow_cards),
                int(row.red_cards),
            ))
        print(f"  player_match_stats rows to insert: {len(pms_rows)}")

        # 10. Write in a transaction. Order: augment players, wipe season
        # downstream tables, re-insert games, re-insert player_match_stats.
        seasons = sorted(SEASON_MAP.keys())
        print(f"\nBeginning transaction (wipe + reload for "
              f"seasons {seasons})...")
        con.execute("BEGIN TRANSACTION")
        try:
            # 10a. Add new players first (FK from player_match_stats needs them).
            if new_players_to_insert:
                con.executemany(
                    "INSERT OR IGNORE INTO players (player_id, "
                    "player_name) VALUES (?, ?)",
                    new_players_to_insert,
                )
                print(f"  Inserted {len(new_players_to_insert)} new "
                      f"players.")

            # 10b. Wipe child tables of games FIRST (FK ordering):
            #   - player_match_stats.game_id -> games.game_id (S10/A1)
            #   - team_match_stats.game_id   -> games.game_id (S10/A2)
            # Both must be empty for the given season before games can
            # be wiped, or DuckDB raises ConstraintException.
            for season in seasons:
                con.execute(
                    "DELETE FROM player_match_stats WHERE season = ?",
                    [season],
                )
                con.execute(
                    "DELETE FROM team_match_stats WHERE season = ?",
                    [season],
                )
            # 10c. Wipe games (now safe -- all children for these seasons
            # have been wiped above).
            for season in seasons:
                con.execute(
                    "DELETE FROM games WHERE season = ?",
                    [season],
                )

            # 10d. Insert games.
            con.executemany(
                """
                INSERT INTO games
                    (game_id, season, match_date, home_team, away_team)
                VALUES (?, ?, ?, ?, ?)
                """,
                games_rows,
            )

            # 10e. Insert player_match_stats.
            con.executemany(
                """
                INSERT INTO player_match_stats (
                    game_id, player_id, season, team,
                    position, effective_position, position_id,
                    minutes, goals, own_goals, shots,
                    xg, xg_chain, xg_buildup,
                    assists, xa, key_passes,
                    yellow_cards, red_cards
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pms_rows,
            )

            # 10f. Verify counts before COMMIT.
            games_count = con.execute(
                "SELECT COUNT(*) FROM games"
            ).fetchone()[0]
            pms_count = con.execute(
                "SELECT COUNT(*) FROM player_match_stats"
            ).fetchone()[0]
            if games_count != len(games_rows):
                raise SystemExit(
                    f"games insert mismatch: tried {len(games_rows)}, "
                    f"see {games_count}. Rolling back."
                )
            if pms_count != len(pms_rows):
                raise SystemExit(
                    f"player_match_stats insert mismatch: tried "
                    f"{len(pms_rows)}, see {pms_count}. Rolling back."
                )

            con.execute("COMMIT")
            print(f"\nCOMMITTED. {games_count} games, "
                  f"{pms_count} player_match_stats rows.")
        except Exception:
            print("!!! Error during writes, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 11. Sanity output.
        print(f"\n--- player_match_stats rows per season ---")
        for r in con.execute(
            """
            SELECT season, COUNT(*) AS n,
                   COUNT(DISTINCT player_id) AS n_players,
                   COUNT(DISTINCT game_id) AS n_games
            FROM player_match_stats
            GROUP BY season
            ORDER BY season
            """
        ).fetchall():
            print(f"  {r[0]}  rows={r[1]:>5}  "
                  f"players={r[2]:>4}  games={r[3]:>4}")

        print(f"\n--- effective_position vs raw position (top 10 "
              f"effective_positions) ---")
        for r in con.execute(
            """
            SELECT effective_position, COUNT(*) AS n,
                   SUM(CASE WHEN position = 'Sub' THEN 1 ELSE 0 END)
                       AS from_sub
            FROM player_match_stats
            GROUP BY effective_position
            ORDER BY n DESC
            LIMIT 15
            """
        ).fetchall():
            print(f"  {r[0]:<6}  rows={r[1]:>5}  (of which "
                  f"backfilled-from-Sub: {r[2]})")

        print(f"\n--- Sample player: Salah's per-match positions in "
              f"2025-2026 (first 5) ---")
        for r in con.execute(
            """
            SELECT g.match_date, pms.team, g.home_team, g.away_team,
                   pms.position, pms.effective_position, pms.minutes,
                   pms.xg, pms.xa
            FROM player_match_stats pms
            JOIN games g USING (game_id)
            JOIN players p ON p.player_id = pms.player_id
            WHERE p.player_name = 'Mohamed Salah'
              AND pms.season = '2025-2026'
            ORDER BY g.match_date
            LIMIT 5
            """
        ).fetchall():
            print(f"  {r[0]}  {r[1]:<10}  ({r[2]} vs {r[3]:<20})  "
                  f"pos={r[4]:<5} eff={r[5]:<5}  min={r[6]:>3}  "
                  f"xG={r[7]:.2f} xA={r[8]:.2f}")
    finally:
        con.close()


if __name__ == "__main__":
    main()