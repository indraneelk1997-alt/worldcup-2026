"""
Creates the fixtures and fixture_lineups tables in worldcup.duckdb.
Idempotent: safe to re-run. Drops child table before parent (FK rule).
"""
import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

DDL = """
DROP TABLE IF EXISTS fixture_lineups;
DROP TABLE IF EXISTS fixtures;

CREATE TABLE fixtures (
    fixture_id   VARCHAR PRIMARY KEY,
    season       VARCHAR NOT NULL,
    match_date   DATE    NOT NULL,
    home_team    VARCHAR NOT NULL,
    away_team    VARCHAR NOT NULL,
    matchday     INTEGER
);

CREATE TABLE fixture_lineups (
    fixture_id   VARCHAR NOT NULL,
    team         VARCHAR NOT NULL,
    player_id    INTEGER NOT NULL,
    is_starter   BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (fixture_id, player_id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id),
    FOREIGN KEY (player_id)  REFERENCES players(player_id)
);
"""

def main():
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(DDL)
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        print("Tables in worldcup.duckdb:")
        for (t,) in tables:
            print(f"  - {t}")
    finally:
        con.close()

if __name__ == "__main__":
    main()