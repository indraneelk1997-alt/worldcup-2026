"""
V1.02 modeling — STEP 5b cont.: backfill player_positions.

WHAT THIS DOES
    Reads per-season position data from Understat (via local soccerdata
    cache), decodes ALL non-S tokens in the position string (not just the
    first), and writes one row per (player, season, team, class) to
    player_positions.

    Example: a player listed as 'D F M S' for the 2025-2026 season gets
    THREE rows:
      (player_id, '2025-2026', team, 'DEF', priority=1)
      (player_id, '2025-2026', team, 'FWD', priority=2)
      (player_id, '2025-2026', team, 'MID', priority=3)

    The 'S' token is ignored (it signals substitute appearances, not a
    primary position).

VOCABULARY DECODING (same rules as add_position_class_column.py)
    'GK' -> 'GK'
    'D'  -> 'DEF'
    'M'  -> 'MID'
    'F'  -> 'FWD'
    'S'  -> ignored

SEASON STRING NORMALIZATION (same as backfill_position_class.py)
    Understat returns '2425' / '2526'; our DB uses '2024-2025' / '2025-2026'.
    SEASON_MAP handles the translation.

CONSISTENCY GUARANTEE
    After this script runs, for every row in player_season_stats:
      player_season_stats.position_class == player_positions.position_class
        where player_positions.priority = 1
    AND player_positions has 1-4 rows for that (player, season, team).

    The script also verifies this invariant before COMMIT and rolls back
    if it ever fails. This catches drift between the two stores.

IDEMPOTENCY
    Wipes player_positions for the seasons we're loading and re-inserts.
    Re-running on the same data produces the same rows.

HOW TO RUN
    From the repo root:
        uv run python src/model/backfill_player_positions.py
"""

import duckdb
import soccerdata as sd
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

SEASON_MAP = {
    "2024-2025": "2425",
    "2025-2026": "2526",
}

CODE_TO_CLASS = {
    "GK": "GK",
    "D":  "DEF",
    "M":  "MID",
    "F":  "FWD",
}


def decode_position_all(pos_string):
    """
    Return a list of (position_class, priority) tuples for ALL non-S
    tokens in the position string. Priority is 1-based in order of
    appearance (Understat's most-to-least-played order).
    """
    if pos_string is None:
        return []
    try:
        s = str(pos_string).strip()
    except Exception:
        return []
    if not s or s.lower() in ("nan", "<na>", "none"):
        return []
    tokens = [t for t in s.split() if t != "S"]
    out = []
    seen_classes = set()
    for i, tok in enumerate(tokens, start=1):
        cls = CODE_TO_CLASS.get(tok)
        if cls is None:
            continue
        if cls in seen_classes:
            # Defensive: if Understat ever lists the same class twice
            # (e.g. 'D D F'), only keep the first occurrence.
            continue
        seen_classes.add(cls)
        out.append((cls, i))
    return out


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # 1. Pull position strings from Understat (cached).
    print("Loading Understat season stats (uses local soccerdata cache)...")
    us = sd.Understat(
        leagues="ENG-Premier League",
        seasons=list(SEASON_MAP.keys()),
    )
    df = us.read_player_season_stats().reset_index()
    print(f"  Loaded {len(df)} raw rows.")

    sd_to_db_season = {sd: db for db, sd in SEASON_MAP.items()}
    sd_to_db_season.update({db: db for db in SEASON_MAP})  # passthrough

    # 2. Build the row lookup. We'll only insert rows that match an
    # existing (player_id, season, team) in player_season_stats, so we
    # don't backfill for rows our loader filtered out (sub-450-min).
    lookup_rows = []  # list of (player_id, db_season, team, class, priority)
    for _, row in df.iterrows():
        pos_decoded = decode_position_all(row["position"])
        if not pos_decoded:
            continue
        db_season = sd_to_db_season.get(str(row["season"]))
        if db_season is None:
            continue
        pid = int(row["player_id"])
        team = str(row["team"])
        for cls, prio in pos_decoded:
            lookup_rows.append((pid, db_season, team, cls, prio))

    print(f"  Decoded {len(lookup_rows)} (player, season, team, class) rows.")

    # 3. Apply in a transaction.
    con = duckdb.connect(str(DB_PATH))
    try:
        # Sanity: required tables exist.
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if "player_positions" not in existing:
            raise SystemExit(
                "player_positions table missing. Run "
                "player_positions_schema.py first."
            )

        # Snapshot pre-state.
        pss_count = con.execute(
            "SELECT COUNT(*) FROM player_season_stats"
        ).fetchone()[0]
        print(f"\nplayer_season_stats has {pss_count} rows.")

        # Filter lookup to only rows present in player_season_stats.
        # (Sub-450-min players are in Understat but not in our DB; their
        # position rows would have no parent.)
        pss_keys = {
            (r[0], r[1], r[2])
            for r in con.execute(
                "SELECT player_id, season, team FROM player_season_stats"
            ).fetchall()
        }
        filtered_rows = [
            row for row in lookup_rows
            if (row[0], row[1], row[2]) in pss_keys
        ]
        skipped = len(lookup_rows) - len(filtered_rows)
        print(f"  {len(filtered_rows)} rows match player_season_stats.")
        print(f"  {skipped} rows skipped (no matching player-season-team in our DB).")

        # Insert in a transaction. Wipe the relevant seasons first.
        seasons = sorted(SEASON_MAP.keys())
        print(f"\nClearing player_positions for seasons {seasons}...")
        con.execute("BEGIN TRANSACTION")
        try:
            for season in seasons:
                con.execute(
                    "DELETE FROM player_positions WHERE season = ?",
                    [season],
                )

            con.executemany(
                """
                INSERT INTO player_positions
                    (player_id, season, team, position_class, priority)
                VALUES (?, ?, ?, ?, ?)
                """,
                filtered_rows,
            )

            inserted = con.execute(
                "SELECT COUNT(*) FROM player_positions"
            ).fetchone()[0]
            print(f"  Inserted {inserted} rows.")
            if inserted != len(filtered_rows):
                raise SystemExit(
                    f"Insert mismatch: tried {len(filtered_rows)}, "
                    f"see {inserted}. Rolling back."
                )

            # Consistency check: every (player_id, season, team) in
            # player_season_stats should have a priority=1 row in
            # player_positions whose class matches position_class.
            mismatches = con.execute(
                """
                SELECT pss.player_id, pss.season, pss.team,
                       pss.position_class AS pss_class,
                       pp.position_class AS pp_class
                FROM player_season_stats pss
                LEFT JOIN player_positions pp
                  ON pp.player_id = pss.player_id
                 AND pp.season    = pss.season
                 AND pp.team      = pss.team
                 AND pp.priority  = 1
                WHERE pp.position_class IS NULL
                   OR pp.position_class != pss.position_class
                """
            ).fetchall()
            if mismatches:
                print(f"\n!!! Found {len(mismatches)} consistency mismatches "
                      "between position_class and priority=1 row:")
                for m in mismatches[:10]:
                    print(f"  {m}")
                raise SystemExit("Consistency check failed. Rolling back.")

            con.execute("COMMIT")
            print("\nCOMMITTED. Consistency invariant holds.")
        except Exception:
            print("!!! Error during insert, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 4. Show distributions for sanity.
        print("\n--- Multi-position breakdown by season ---")
        rows = con.execute(
            """
            WITH counts_per_player AS (
                SELECT player_id, season, team, COUNT(*) AS n_classes
                FROM player_positions
                GROUP BY player_id, season, team
            )
            SELECT season, n_classes, COUNT(*) AS n_players
            FROM counts_per_player
            GROUP BY season, n_classes
            ORDER BY season, n_classes
            """
        ).fetchall()
        print(f"{'season':<12} {'n_classes':>9} {'n_players':>10}")
        for season, n_classes, n_players in rows:
            print(f"{season:<12} {n_classes:>9} {n_players:>10}")

        print("\n--- Sample multi-position players (2025-2026) ---")
        rows = con.execute(
            """
            SELECT p.player_name, pp.team,
                   STRING_AGG(pp.position_class, ',' ORDER BY pp.priority)
                       AS classes,
                   pss.minutes
            FROM player_positions pp
            JOIN players p USING (player_id)
            JOIN player_season_stats pss
              ON pss.player_id = pp.player_id
             AND pss.season    = pp.season
             AND pss.team      = pp.team
            WHERE pp.season = '2025-2026'
            GROUP BY p.player_name, pp.team, pp.player_id, pss.minutes
            HAVING COUNT(*) > 1
            ORDER BY pss.minutes DESC
            LIMIT 12
            """
        ).fetchall()
        print(f"{'player':<26} {'team':<16} {'classes':<14} {'min':>5}")
        for name, team, classes, mins in rows:
            print(f"{name[:26]:<26} {team[:16]:<16} {classes:<14} {mins:>5}")
    finally:
        con.close()


if __name__ == "__main__":
    main()