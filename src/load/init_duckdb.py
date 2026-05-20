"""
Initialize the project DuckDB database and load V1.01 ratings.

Reads:  data/processed/player_ratings_v101_<season>.csv
Writes: data/processed/worldcup.duckdb

Behavior:
- Creates two tables: `players` (identity) and `player_season_stats` (observations).
- Drops and recreates both tables on every run (V1.01 is small, idempotency > speed).
- Adds a literal `season` column during load (the CSV doesn't carry it explicitly).

V1.02+ will add:
- `teams` table (currently we just store team name as a string)
- `matches` table (for opponent context)
- Incremental loading instead of drop-and-recreate
"""

import logging
from pathlib import Path

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROCESSED_DATA_DIR / "worldcup.duckdb"


def init_database(season: str = "2024-2025") -> None:
    """Create schema and load V1.01 ratings into DuckDB."""
    csv_path = PROCESSED_DATA_DIR / f"player_ratings_v101_{season}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Ratings CSV not found: {csv_path}\n"
            f"Run src/transform/compute_ratings.py first."
        )

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # WHY: connect() creates the file if it doesn't exist, opens it if it does.
    # No separate "create database" step needed in DuckDB.
    logger.info(f"Connecting to DuckDB at {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))

    try:
        # ── Create `players` table ──────────────────────────────────────
        # WHY: IF NOT EXISTS makes this idempotent across multiple seasons.
        # Previous versions used DROP TABLE which destroyed cross-season data.
        con.execute("""
            CREATE TABLE IF NOT EXISTS players (
                player_id    INTEGER  PRIMARY KEY,
                player_name  VARCHAR  NOT NULL
            )
        """)
        logger.info("Created table: players")

        # ── Create `player_season_stats` table ──────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS player_season_stats (
                player_id      INTEGER  NOT NULL REFERENCES players(player_id),
                season         VARCHAR  NOT NULL,
                team           VARCHAR  NOT NULL,
                team_id        INTEGER,
                position       VARCHAR,
                matches        INTEGER,
                minutes        INTEGER  NOT NULL,
                goals          INTEGER,
                assists        INTEGER,
                np_xg          DOUBLE,
                xa             DOUBLE,
                rating_per_90  DOUBLE,
                PRIMARY KEY (player_id, season, team)
            )
        """)
        logger.info("Created table: player_season_stats")

        # ── Load players (deduped) from the CSV ─────────────────────────
        # WHY: a player might appear across multiple seasons. INSERT OR IGNORE
        # skips rows whose player_id already exists (PK conflict) without raising
        # an error. Same player_id always means the same player, so this is safe.
        con.execute(f"""
            INSERT OR IGNORE INTO players (player_id, player_name)
            SELECT DISTINCT player_id, player AS player_name
            FROM read_csv_auto('{csv_path}')
        """)
        player_count = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        logger.info(f"Loaded {player_count} unique players")

        # ── Load player_season_stats rows from the CSV ──────────────────
        # WHY: literal '{season}' is the season for *this load* — the CSV itself
        # doesn't carry season info, only the filename does. We attach it here.
        con.execute(f"""
            INSERT INTO player_season_stats (
                player_id, season, team, team_id, position, matches, minutes,
                goals, assists, np_xg, xa, rating_per_90
            )
            SELECT
                player_id,
                '{season}' AS season,
                team,
                team_id,
                position,
                matches,
                minutes,
                goals,
                assists,
                np_xg,
                xa,
                rating_per_90
            FROM read_csv_auto('{csv_path}')
        """)
        stats_count = con.execute(
            "SELECT COUNT(*) FROM player_season_stats"
        ).fetchone()[0]
        logger.info(f"Loaded {stats_count} player-season-team rows")

    finally:
        # WHY: always close the connection, even if an error happened above.
        # DuckDB connections hold a file lock; leaving them open between
        # script runs (e.g. in a notebook) causes "database is locked" errors.
        con.close()
        logger.info("Closed DuckDB connection")


if __name__ == "__main__":
    init_database()