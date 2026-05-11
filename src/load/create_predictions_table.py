"""
Creates the predictions table in worldcup.duckdb.
Stores aggregate output of a simulator run with all parameters
needed for reproducibility and later backtesting.
"""
import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

DDL = """
DROP TABLE IF EXISTS predictions;

CREATE TABLE predictions (
    prediction_id     VARCHAR PRIMARY KEY,
    fixture_id        VARCHAR NOT NULL,
    model_version     VARCHAR NOT NULL,
    run_timestamp     TIMESTAMP NOT NULL,
    n_simulations     INTEGER NOT NULL,
    rng_seed          INTEGER NOT NULL,
    base_goals        DOUBLE  NOT NULL,
    k_param           DOUBLE  NOT NULL,
    home_strength     DOUBLE  NOT NULL,
    away_strength     DOUBLE  NOT NULL,
    xg_home           DOUBLE  NOT NULL,
    xg_away           DOUBLE  NOT NULL,
    p_home_win        DOUBLE  NOT NULL,
    p_draw            DOUBLE  NOT NULL,
    p_away_win        DOUBLE  NOT NULL,
    avg_home_goals    DOUBLE  NOT NULL,
    avg_away_goals    DOUBLE  NOT NULL,
    modal_scoreline   VARCHAR NOT NULL,
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
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