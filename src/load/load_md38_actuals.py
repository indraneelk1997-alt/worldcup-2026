"""
TEMPORARY (S14) — Append MD38 actuals to games + player_match_stats +
                  team_match_stats. NOT the canonical loader.

THIS SCRIPT IS NOT THE CANONICAL LOADER. It exists because the canonical
loaders (backfill_player_match.py + team_match_load.py) use a destructive
wipe-and-reload pattern that breaks when new FK-child tables are added to
the schema (S14 encountered this — game_id 26602 was held alive by a
combination of FK children, some of which DuckDB's information_schema
did not report). Fixing the canonical loader properly is a separate
architectural task (Model B append-only ingest, see S14 carry-forward).

WHAT THIS DOES
    Pulls 2025-2026 Understat per-match and per-player-match data
    (cache-hit, fast), filters to the 10 MD38 fixtures (matchday 38,
    kickoff 2026-05-24), and APPENDS rows to:
      - players                 (INSERT OR IGNORE; any new MD38 subs)
      - games                   (INSERT OR IGNORE; 10 new rows)
      - player_match_stats      (INSERT OR IGNORE; ~250 new rows)
      - team_match_stats        (INSERT OR IGNORE; 20 new rows)

    All operations are append-only. No DELETE statements. No truncation.
    No FK-cascade complications. No risk of clobbering computed state
    (team_season_strength_v103, league_averages_v103, club_elo,
    md38_predictions_b12, md38_score_grid_b12, model_parameters_v103).

EFFECTIVE_POSITION POLICY
    Lifted verbatim from backfill_player_match.py (policy-C, 3-step
    chain). Critical: compute player_primary across the FULL season's
    non-Sub rows, THEN filter to MD38 for insertion. Filtering before
    would give a player_primary based on only ~10 matches of context,
    diverging from what the canonical loader produces.

IDENTIFYING MD38 FIXTURES
    Two filters used together for safety:
      - match_date == 2026-05-24 (the published kickoff date)
      - home/away teams ∈ the 10 known MD38 pairings from fixtures table

REFERENCES THE CANONICAL LOADERS
    - src/load/backfill_player_match.py     (games + player_match_stats)
    - src/load/team_match_load.py           (team_match_stats)
    Column lists, schema, and effective_position policy are matched to
    those scripts. Any drift between this script and the canonical
    loaders is a bug.

HOW TO RUN
    From the repo root, AFTER MD38 actuals are available on Understat:
        uv run python src/load/load_md38_actuals.py
"""

import sys
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd
import soccerdata as sd

DB_PATH = Path("data/processed/worldcup.duckdb")
TARGET_SEASON_DB = "2025-2026"   # DB convention
TARGET_SEASON_UNDERSTAT = "2526"  # Understat convention
MD38_DATE = pd.to_datetime("2026-05-24").date()

# Same as canonical loader.
CLASS_TO_POSITION = {
    "GK":  "GK",
    "DEF": "DC",
    "MID": "MC",
    "FWD": "FW",
}


# ---------------------------------------------------------------------------
# Verbatim copy from src/load/backfill_player_match.py (policy-C).
# Any drift is a bug — keep this in sync if the canonical policy changes.
# ---------------------------------------------------------------------------
def compute_effective_position(df, season_stats_class_lookup):
    non_sub = df[df["position"] != "Sub"]
    player_pos_counter = {}
    for pid, pos in zip(non_sub["player_id"], non_sub["position"]):
        player_pos_counter.setdefault(int(pid), Counter())[pos] += 1
    player_primary = {}
    for pid, ctr in player_pos_counter.items():
        player_primary[pid] = ctr.most_common(1)[0][0]

    eff_lookup = {}
    sub_only_count = 0
    fallback_to_class_count = 0
    fallback_to_sub_count = 0
    for game_id, pid, pos in zip(df["game_id"], df["player_id"],
                                  df["position"]):
        key = (int(game_id), int(pid))
        if pos != "Sub":
            eff_lookup[key] = pos
            continue
        primary = player_primary.get(int(pid))
        if primary is not None:
            eff_lookup[key] = primary
            continue
        sub_only_count += 1
        season_class = season_stats_class_lookup.get(int(pid))
        if season_class is not None:
            mapped = CLASS_TO_POSITION.get(season_class)
            if mapped is not None:
                eff_lookup[key] = mapped
                fallback_to_class_count += 1
                continue
        eff_lookup[key] = "Sub"
        fallback_to_sub_count += 1

    print(f"  Sub-only players (computed over full season context): "
          f"{sub_only_count} rows affected")
    print(f"    of which backfilled from season_stats class: "
          f"{fallback_to_class_count}")
    print(f"    of which kept as 'Sub' (no class either): "
          f"{fallback_to_sub_count}")
    return eff_lookup


def parse_game_string(game_str):
    try:
        return pd.to_datetime(game_str.split(" ", 1)[0]).date()
    except Exception:
        return None


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Get the 10 MD38 fixture pairings from the fixtures table
        # so we can sanity-check Understat against our pre-loaded slate.
        md38_pairings = set()
        for home, away in con.execute("""
            SELECT home_team, away_team FROM fixtures
            WHERE matchday = 38 AND season = ?
        """, [TARGET_SEASON_DB]).fetchall():
            md38_pairings.add((home, away))
        if len(md38_pairings) != 10:
            raise SystemExit(
                f"Expected 10 MD38 fixture pairings, found "
                f"{len(md38_pairings)}."
            )
        print(f"Loaded {len(md38_pairings)} MD38 fixture pairings "
              f"from fixtures table.")

        # 2. Pull Understat per-PLAYER-match for full 2025-26 season.
        # We need full-season data for the effective_position policy
        # (player_primary computed across all matches, not just MD38).
        print(f"\nLoading Understat per-player-match for "
              f"season {TARGET_SEASON_UNDERSTAT} (cache hit expected)...")
        understat = sd.Understat(
            leagues="ENG-Premier League",
            seasons=TARGET_SEASON_UNDERSTAT,
        )
        df_player = understat.read_player_match_stats().reset_index()
        print(f"  Loaded {len(df_player)} player-match rows for full season.")

        # 3. Pull Understat per-TEAM-match for full 2025-26 (wide format).
        print(f"\nLoading Understat per-team-match for "
              f"season {TARGET_SEASON_UNDERSTAT} (cache hit expected)...")
        df_team = understat.read_team_match_stats().reset_index()
        print(f"  Loaded {len(df_team)} team-match rows (wide format).")

        # 4. Normalize types. Understat returns game_id, player_id as
        # strings sometimes; coerce.
        df_player["game_id"] = df_player["game_id"].astype(int)
        df_player["player_id"] = df_player["player_id"].astype(int)
        df_team["game_id"] = df_team["game_id"].astype(int)

        # 5. Compute effective_position on FULL season df. Then filter.
        # Build season_class_lookup from existing player_season_stats.
        season_class_lookup = {
            r[0]: r[1] for r in con.execute(
                "SELECT player_id, position_class FROM player_season_stats"
            ).fetchall()
        }
        print(f"\nLoaded {len(season_class_lookup)} season-class lookups.")
        print("Computing effective_position over FULL season (policy C)...")
        eff_lookup = compute_effective_position(df_player, season_class_lookup)

        # 6. Extract MD38 game_ids from team-match data (it has the
        # canonical `date` column as a timestamp). Filter to MD38_DATE.
        df_team["match_date"] = pd.to_datetime(df_team["date"]).dt.date
        df_team_md38 = df_team[df_team["match_date"] == MD38_DATE].copy()
        md38_game_ids = sorted(df_team_md38["game_id"].unique().tolist())
        print(f"\nMD38 game_ids in Understat data: "
              f"{len(md38_game_ids)} fixtures: {md38_game_ids}")
        if len(md38_game_ids) != 10:
            raise SystemExit(
                f"Expected exactly 10 MD38 game_ids, found "
                f"{len(md38_game_ids)}."
            )

        # Also filter player-match to MD38 game_ids (player rows don't
        # have a clean date column; use game_id membership).
        df_player_md38 = df_player[
            df_player["game_id"].isin(md38_game_ids)
        ].copy()

        # 7. Build games rows. Cross-check pairings against fixtures table.
        games_rows = []
        for _, r in df_team_md38.iterrows():
            gid = int(r["game_id"])
            home = r["home_team"]
            away = r["away_team"]
            date = r["match_date"]
            if (home, away) not in md38_pairings:
                raise SystemExit(
                    f"Pairing mismatch for game {gid}: ({home}, {away}) "
                    f"not in fixtures table's MD38 pairings."
                )
            games_rows.append((gid, TARGET_SEASON_DB, date, home, away))
        print(f"\nBuilt {len(games_rows)} games rows. Pairings verified "
              f"against fixtures table.")

        # 8. Build player_match_stats rows for MD38 only.
        # Columns must match the canonical INSERT in backfill_player_match.py:
        #   game_id, player_id, season, team, position, effective_position,
        #   position_id, minutes, goals, own_goals, shots, xg, xg_chain,
        #   xg_buildup, assists, xa, key_passes, yellow_cards, red_cards
        pms_rows = []
        new_players = {}  # player_id -> player_name for INSERT OR IGNORE
        existing_player_ids = {
            r[0] for r in con.execute("SELECT player_id FROM players").fetchall()
        }
        for _, r in df_player_md38.iterrows():
            gid = int(r["game_id"])
            pid = int(r["player_id"])
            pms_rows.append((
                gid, pid, TARGET_SEASON_DB, r["team"],
                r["position"], eff_lookup[(gid, pid)],
                int(r["position_id"]),
                int(r["minutes"]),
                int(r["goals"]),
                int(r["own_goals"]),
                int(r["shots"]),
                float(r["xg"]),
                float(r["xg_chain"]),
                float(r["xg_buildup"]),
                int(r["assists"]),
                float(r["xa"]),
                int(r["key_passes"]),
                int(r["yellow_cards"]),
                int(r["red_cards"]),
            ))
            if pid not in existing_player_ids and pid not in new_players:
                new_players[pid] = r["player"]
        print(f"Built {len(pms_rows)} player_match_stats rows.")
        if new_players:
            print(f"  {len(new_players)} new players to insert "
                  f"(MD38 debutants or late additions).")

        # 9. Build team_match_stats rows for MD38 only.
        # Understat wide format: one row per match with home_/away_
        # prefixed cols. Our DB stores long: two rows per match
        # (home + away perspectives).
        tms_rows = []
        for _, r in df_team_md38.iterrows():
            gid = int(r["game_id"])
            home, away = r["home_team"], r["away_team"]
            # Home perspective
            tms_rows.append((
                gid, home, "home", TARGET_SEASON_DB, away,
                int(r["home_points"]),
                float(r["home_expected_points"]),
                int(r["home_goals"]),
                int(r["away_goals"]),
                float(r["home_xg"]),
                float(r["away_xg"]),
                float(r["home_np_xg"]),
                float(r["away_np_xg"]),
                float(r["home_np_xg"]) - float(r["away_np_xg"]),
                float(r["home_ppda"]),
                float(r["away_ppda"]),
                int(r["home_deep_completions"]),
                int(r["away_deep_completions"]),
            ))
            # Away perspective (everything swapped)
            tms_rows.append((
                gid, away, "away", TARGET_SEASON_DB, home,
                int(r["away_points"]),
                float(r["away_expected_points"]),
                int(r["away_goals"]),
                int(r["home_goals"]),
                float(r["away_xg"]),
                float(r["home_xg"]),
                float(r["away_np_xg"]),
                float(r["home_np_xg"]),
                float(r["away_np_xg"]) - float(r["home_np_xg"]),
                float(r["away_ppda"]),
                float(r["home_ppda"]),
                int(r["away_deep_completions"]),
                int(r["home_deep_completions"]),
            ))
        print(f"Built {len(tms_rows)} team_match_stats rows "
              f"(10 matches × 2 perspectives).")

        # 10. APPEND in a transaction. INSERT OR IGNORE everywhere.
        print(f"\nBeginning transaction (APPEND-ONLY, INSERT OR IGNORE)...")
        con.execute("BEGIN TRANSACTION")
        try:
            # Players first (FK parent for player_match_stats).
            if new_players:
                con.executemany(
                    "INSERT OR IGNORE INTO players "
                    "(player_id, player_name) VALUES (?, ?)",
                    list(new_players.items()),
                )
                print(f"  Inserted {len(new_players)} players (or ignored).")

            # Games next (FK parent for player_match_stats + team_match_stats).
            con.executemany(
                """
                INSERT OR IGNORE INTO games
                    (game_id, season, match_date, home_team, away_team)
                VALUES (?, ?, ?, ?, ?)
                """,
                games_rows,
            )
            print(f"  Inserted {len(games_rows)} games (or ignored).")

            # Player_match_stats.
            con.executemany(
                """
                INSERT OR IGNORE INTO player_match_stats (
                    game_id, player_id, season, team,
                    position, effective_position, position_id,
                    minutes, goals, own_goals, shots,
                    xg, xg_chain, xg_buildup,
                    assists, xa, key_passes,
                    yellow_cards, red_cards
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pms_rows,
            )
            print(f"  Inserted {len(pms_rows)} player_match_stats "
                  f"(or ignored).")

            # Team_match_stats.
            con.executemany(
                """
                INSERT OR IGNORE INTO team_match_stats (
                    game_id, team, side, season, opponent,
                    points, expected_points, goals, opponent_goals,
                    xg, opponent_xg, np_xg, opponent_np_xg,
                    np_xg_difference, ppda, opponent_ppda,
                    deep_completions, opponent_deep_completions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?)
                """,
                tms_rows,
            )
            print(f"  Inserted {len(tms_rows)} team_match_stats "
                  f"(or ignored).")

            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            print("!!! Error during writes, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 11. Post-load verification.
        print(f"\n{'='*60}")
        print(f"POST-LOAD ROW COUNTS")
        print(f"{'='*60}")
        for t in ("players", "games", "player_match_stats",
                  "team_match_stats"):
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n}")

        # Show MD38 actuals from team_match_stats (home perspective).
        print(f"\n--- MD38 actual scorelines (home perspective) ---")
        print(con.execute(f"""
            SELECT t.game_id, t.team AS home_team, t.opponent AS away_team,
                   t.goals AS home_goals, t.opponent_goals AS away_goals,
                   ROUND(t.xg, 2) AS home_xg, ROUND(t.opponent_xg, 2) AS away_xg
            FROM team_match_stats t
            WHERE t.side = 'home' AND t.game_id IN ({','.join(map(str, md38_game_ids))})
            ORDER BY t.game_id
        """).fetchdf().to_string())
    finally:
        con.close()


if __name__ == "__main__":
    main()