"""
V1.02 modeling — STEP 4 prep (cont.): backfill position_class.

WHAT THIS DOES
    Reads per-season player position data from Understat via soccerdata
    (hits the local cache populated by V1.01's loader — no network call
    in the normal case), decodes the position string into a class, and
    UPDATEs player_season_stats.position_class.

THE POSITION DECODER
    Understat returns `position` as a space-separated string of single-
    letter codes, ordered most-to-least played that season:
      'D'  -> Defender
      'M'  -> Midfielder
      'F'  -> Forward
      'GK' -> Goalkeeper (two letters, distinct from D/M/F)
      'S'  -> Substitute appearance (signal, not a primary position)
    Examples from real data: 'D S', 'M S', 'F M S', 'GK', 'D F M S'.

    Decoder rule: take the first non-'S' token, map letter -> class.
    Multi-position players (e.g. 'F M S') get classed by primary position.
    Players whose only entry is 'S' have no primary position recorded —
    all 134 such rows in current data are below the 450-min loader floor,
    so they don't appear in our DB. The decoder still returns NULL for
    them as a safety net.

SEASON STRING TRANSLATION
    Our DB stores seasons as '2024-2025' / '2025-2026'.
    soccerdata's DataFrame multi-index uses a 4-digit form: '2425' / '2526'
    (start-year + end-year, last two digits each).
    The mapping is a small dict at the top of the script.

JOIN GRAIN
    Updates by (player_id, season, team). Same as our existing PK.
    A row that exists in our DB but not in the latest Understat DataFrame
    is left NULL — we don't fabricate data.

HOW TO RUN
    From the repo root:
        uv run python src/model/backfill_position_class.py
    Re-running is safe: writes the same values to the same rows.
"""

import duckdb
import soccerdata as sd
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# DB-side -> soccerdata-side season string.
SEASON_MAP = {
    "2024-2025": "2425",
    "2025-2026": "2526",
}

# Map Understat single-letter primary code -> our position_class vocabulary.
CODE_TO_CLASS = {
    "GK": "GK",
    "D":  "DEF",
    "M":  "MID",
    "F":  "FWD",
}


def decode_position(pos_string):
    """Return one of GK / DEF / MID / FWD, or None if undecodable."""
    if pos_string is None:
        return None
    # Defensive: handle pandas NA, NaN, empty string.
    try:
        s = str(pos_string).strip()
    except Exception:
        return None
    if not s or s.lower() in ("nan", "<na>", "none"):
        return None
    tokens = [t for t in s.split() if t != "S"]
    if not tokens:
        return None  # S-only player, no primary position
    return CODE_TO_CLASS.get(tokens[0])


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # === 1. Pull position data from Understat (via local cache) ============
    print("Loading Understat season stats (uses local soccerdata cache)...")
    us = sd.Understat(
        leagues="ENG-Premier League",
        seasons=list(SEASON_MAP.keys()),  # DB-side names; soccerdata accepts these
    )
    df = us.read_player_season_stats()
    print(f"  Loaded {len(df)} raw rows from Understat.")

    # Build (player_id, season, team) -> position_class lookup.
    # The DataFrame has a multi-index (league, season, team, player_name)
    # and player_id is a regular column. We need to join by player_id,
    # season, and team. Use the column form for player_id and team_name,
    # and pull season from the index.
    df = df.reset_index()  # flatten multi-index

    # Figure out which season-form is in the DataFrame. The recon showed
    # the multi-index used '2526' style, but reset_index might expose it
    # differently. We'll handle both forms defensively.
    print("\n  DataFrame columns after reset_index:", list(df.columns))
    print("  Distinct seasons in DataFrame:", sorted(df["season"].unique().tolist()))

    # Build a soccerdata-season -> DB-season inverse map for translation.
    sd_to_db_season = {}
    for db_season, sd_season in SEASON_MAP.items():
        sd_to_db_season[sd_season] = db_season
        sd_to_db_season[db_season] = db_season  # passthrough if already DB form

    # Decode position into class on each row.
    df["position_class"] = df["position"].map(decode_position)
    decoded_count = df["position_class"].notna().sum()
    print(f"  Decoded position_class for {decoded_count} / {len(df)} rows.")

    # Build the lookup dict: (player_id, db_season, team) -> position_class
    lookup = {}
    for _, row in df.iterrows():
        if row["position_class"] is None or row["position_class"] is float("nan"):
            continue
        pc = row["position_class"]
        if pc != pc:  # NaN check (pandas)
            continue
        db_season = sd_to_db_season.get(str(row["season"]))
        if db_season is None:
            continue
        key = (int(row["player_id"]), db_season, str(row["team"]))
        lookup[key] = pc

    print(f"  Built lookup with {len(lookup)} (player, season, team) entries.")

    # === 2. UPDATE player_season_stats row-by-row, in a transaction =========
    con = duckdb.connect(str(DB_PATH))
    try:
        # Verify the column exists.
        cols = {
            row[0] for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }
        if "position_class" not in cols:
            raise SystemExit(
                "position_class column not on player_season_stats. "
                "Run add_position_class_column.py first."
            )

        # Snapshot row count before for the post-update verify.
        total_db_rows = con.execute(
            "SELECT COUNT(*) FROM player_season_stats"
        ).fetchone()[0]
        print(f"\nDB has {total_db_rows} player_season_stats rows.")

        # Apply updates in a single transaction. UPDATE one row at a time —
        # ~793 rows, no perf concern.
        print("Applying updates...")
        con.execute("BEGIN TRANSACTION")
        try:
            updated = 0
            for (player_id, db_season, team), pc in lookup.items():
                res = con.execute(
                    """
                    UPDATE player_season_stats
                    SET position_class = ?
                    WHERE player_id = ? AND season = ? AND team = ?
                    """,
                    [pc, player_id, db_season, team],
                )
                # DuckDB UPDATE doesn't return affected count cleanly via
                # this API, but we can re-query after.
                updated += 1

            # === 3. Verify before commit ===================================
            null_count = con.execute(
                "SELECT COUNT(*) FROM player_season_stats "
                "WHERE position_class IS NULL"
            ).fetchone()[0]

            class_dist = con.execute(
                """
                SELECT position_class, COUNT(*) AS n
                FROM player_season_stats
                GROUP BY position_class
                ORDER BY position_class NULLS LAST
                """
            ).fetchall()

            print(f"\nPost-update state:")
            print(f"  Rows with NULL position_class: {null_count}")
            print(f"  Class distribution:")
            for cls, n in class_dist:
                cls_label = cls if cls is not None else "(NULL)"
                pct = 100.0 * n / total_db_rows
                print(f"    {cls_label:<10} {n:>4}  ({pct:5.1f}%)")

            # Sanity check: every class must be in the allowed vocabulary
            # (or NULL). If any other string snuck in, we have a bug.
            allowed = {"GK", "DEF", "MID", "FWD", None}
            bad = [(cls, n) for cls, n in class_dist if cls not in allowed]
            if bad:
                raise SystemExit(
                    f"Found unexpected position_class values: {bad}. "
                    f"Rolling back."
                )

            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            print("!!! Error during update, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # === 4. Show a small sample to eyeball correctness ==================
        print("\n--- Sample: top 10 players by minutes in 2025-2026 ---")
        rows = con.execute(
            """
            SELECT p.player_name, pss.team, pss.position_class,
                   pss.minutes, pss.rating_per_90
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '2025-2026'
            ORDER BY pss.minutes DESC
            LIMIT 10
            """
        ).fetchall()
        print(f"{'player':<26} {'team':<14} {'cls':<5} {'min':>5} {'rating':>7}")
        for name, team, pc, mins, rating in rows:
            print(f"{name[:26]:<26} {team[:14]:<14} {pc or '?':<5} "
                  f"{mins:>5} {rating:>7.3f}")
    finally:
        con.close()


if __name__ == "__main__":
    main()