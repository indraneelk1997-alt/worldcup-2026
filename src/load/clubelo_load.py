"""
V1.03 modeling — STEP 3: ClubElo per-club Elo history ingest.

WHAT THIS DOES
    Pulls Elo rating history from ClubElo for the 20 EPL clubs and
    writes to a new `club_elo` table.
      - Bypasses the broken `sd.ClubElo` soccerdata wrapper (S10
        showed _season_ids init bug).
      - Uses ClubElo's public CSV API directly:
          http://api.clubelo.com/{ClubName}
        Returns one row per Elo update for that club through history.
      - Filters to valid_to >= 2024-07-01 to keep just the last 2
        EPL seasons (matches our project scope).
      - Maps ClubElo's club shorthand to our DB's full names.

DATA SOURCE
    ClubElo.com — independently-maintained Elo ratings for European
    clubs, updated daily, free public CSV API. No Cloudflare.
    Methodology: http://clubelo.com/Help
    API docs: http://clubelo.com/API

SCHEMA
    club_elo (
        club        VARCHAR,    -- our DB's full team name
        country     VARCHAR,    -- 'ENG', 'GER', etc.
        level       INTEGER,    -- 1 = top division
        elo         DOUBLE,
        valid_from  DATE,
        valid_to    DATE,
        PRIMARY KEY (club, valid_from)
    )

NAME MAPPING
    ClubElo uses club shorthand. Mapping is hand-built for our 20 EPL
    teams. If we ever expand to other leagues, this needs expansion.

IDEMPOTENCY
    Wipe + reload. Re-running gets fresh ClubElo data.

HOW TO RUN
    From the repo root:
        uv run python src/load/clubelo_load.py
"""

import duckdb
import pandas as pd
import time
from io import StringIO
from datetime import date
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# Cutoff: keep Elo rows whose validity reaches our project's time scope.
# 2024-2025 EPL season starts mid-August 2024.
HISTORY_CUTOFF = date(2024, 7, 1)

# ClubElo's shorthand -> our DB's team name.
# Verified against ClubElo's club listing for current EPL teams.
EPL_CLUB_MAP = {
    "Arsenal":         "Arsenal",
    "AstonVilla":      "Aston Villa",
    "Bournemouth":     "Bournemouth",
    "Brentford":       "Brentford",
    "Brighton":        "Brighton",
    "Burnley":         "Burnley",
    "Chelsea":         "Chelsea",
    "CrystalPalace":   "Crystal Palace",
    "Everton":         "Everton",
    "Fulham":          "Fulham",
    "Leeds":           "Leeds",
    "Liverpool":       "Liverpool",
    "ManCity":         "Manchester City",
    "ManUnited":       "Manchester United",
    "Newcastle":       "Newcastle United",
    "Forest":          "Nottingham Forest",
    "Sunderland":      "Sunderland",
    "Tottenham":       "Tottenham",
    "WestHam":         "West Ham",
    "Wolves":          "Wolverhampton Wanderers",
}


def ensure_schema(con):
    """Create club_elo if it doesn't exist."""
    existing = {
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    if "club_elo" in existing:
        print("`club_elo` already exists.")
        return
    print("Creating `club_elo` table...")
    con.execute("""
        CREATE TABLE club_elo (
            club        VARCHAR NOT NULL,
            country     VARCHAR NOT NULL,
            level       INTEGER NOT NULL,
            elo         DOUBLE  NOT NULL,
            valid_from  DATE    NOT NULL,
            valid_to    DATE    NOT NULL,
            PRIMARY KEY (club, valid_from)
        )
    """)
    print("  Created.")


def fetch_club_history(clubelo_name):
    """
    Fetch one club's full Elo history from ClubElo's CSV API.
    Returns a pandas DataFrame, or None on failure.
    """
    url = f"http://api.clubelo.com/{clubelo_name}"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        print(f"  !!! Failed to fetch {clubelo_name}: {e}")
        return None
    # Empty response = club not found in their system.
    if df.empty:
        print(f"  !!! Empty response for {clubelo_name}")
        return None
    return df


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # 1. Pull each EPL club's history.
    print(f"Pulling Elo history for {len(EPL_CLUB_MAP)} EPL clubs from "
          f"ClubElo...")
    all_rows = []
    skipped_clubs = []
    for clubelo_name, db_name in EPL_CLUB_MAP.items():
        df = fetch_club_history(clubelo_name)
        if df is None:
            skipped_clubs.append((clubelo_name, db_name))
            continue
        # Coerce date columns to date objects.
        df["From"] = pd.to_datetime(df["From"]).dt.date
        df["To"]   = pd.to_datetime(df["To"]).dt.date
        # Filter to our project's history scope.
        df = df[df["To"] >= HISTORY_CUTOFF]
        # Build tuples in our schema order.
        for r in df.itertuples(index=False):
            all_rows.append((
                db_name,         # club (our DB's name)
                str(r.Country),  # country
                int(r.Level),    # level
                float(r.Elo),    # elo
                r.From,          # valid_from
                r.To,            # valid_to
            ))
        # Be polite to ClubElo's servers.
        time.sleep(0.2)

    print(f"  Collected {len(all_rows)} rows across "
          f"{len(EPL_CLUB_MAP) - len(skipped_clubs)} clubs.")
    if skipped_clubs:
        print(f"  Skipped clubs (no data found):")
        for sn, dn in skipped_clubs:
            print(f"    {sn:<15} ({dn})")

    if not all_rows:
        raise SystemExit("No Elo rows collected. Aborting.")

    # 2. Write to DB.
    con = duckdb.connect(str(DB_PATH))
    try:
        ensure_schema(con)

        print(f"\nWiping club_elo and reloading...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM club_elo")
            con.executemany(
                """
                INSERT INTO club_elo
                    (club, country, level, elo, valid_from, valid_to)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                all_rows,
            )
            inserted = con.execute(
                "SELECT COUNT(*) FROM club_elo"
            ).fetchone()[0]
            if inserted != len(all_rows):
                raise SystemExit(
                    f"Insert mismatch: tried {len(all_rows)}, "
                    f"see {inserted}. Rolling back."
                )
            con.execute("COMMIT")
            print(f"COMMITTED. {inserted} Elo rows written.")
        except Exception:
            print("!!! Error during insert, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 3. Sanity output.
        print(f"\n--- Rows per club (last 2 seasons) ---")
        for r in con.execute(
            """
            SELECT club, COUNT(*) AS n,
                   MIN(valid_from) AS earliest,
                   MAX(valid_from) AS latest,
                   ROUND(MIN(elo), 0) AS min_elo,
                   ROUND(MAX(elo), 0) AS max_elo
            FROM club_elo
            GROUP BY club
            ORDER BY MAX(elo) DESC
            """
        ).fetchall():
            print(f"  {r[0]:<24} rows={r[1]:>3}  "
                  f"{r[2]}..{r[3]}  min/max Elo={r[4]}/{r[5]}")

        # 4. Current standings — current Elo per club.
        print(f"\n--- Current Elo (latest row per club) ---")
        for r in con.execute(
            """
            SELECT club, ROUND(elo, 0) AS current_elo, valid_from
            FROM club_elo
            WHERE (club, valid_from) IN (
                SELECT club, MAX(valid_from)
                FROM club_elo
                GROUP BY club
            )
            ORDER BY elo DESC
            """
        ).fetchall():
            print(f"  {r[0]:<24} Elo={r[1]}  (as of {r[2]})")
    finally:
        con.close()


if __name__ == "__main__":
    main()