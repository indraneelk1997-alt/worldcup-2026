"""
V1.03 B1.2: Populate team_match_predictions_b12 from B1.2 model.

For every (game_id, team) in team_match_stats, produce a prediction using
predict_xg() with the calibrated defaults. Two rows per fixture (home + away).

Idempotent: CREATE IF NOT EXISTS + INSERT OR IGNORE. Re-run safe; to refresh
predictions (e.g. after a calibration change), DELETE existing rows first.

The model_version column allows future B1.3 / V1.04 predictions to coexist
in the same table without dropping anything.
"""

import duckdb
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "model"))

from predict_xg_v103 import predict_xg, DB_PATH  # noqa: E402

MODEL_VERSION = "B1.2_v103"


def create_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS team_match_predictions_b12 (
            game_id INTEGER NOT NULL,
            team VARCHAR NOT NULL,
            season VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            opponent VARCHAR NOT NULL,
            predicted_xg DOUBLE NOT NULL,
            attack_x_opp_defense DOUBLE NOT NULL,
            side_multiplier DOUBLE NOT NULL,
            model_version VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (game_id, team, model_version)
        )
    """)


def load_predictions(con: duckdb.DuckDBPyConnection) -> int:
    """For every team-match, compute and insert a prediction.

    We pull the (game_id, team, opponent, side, season) rows from
    team_match_stats, then call predict_xg per fixture. To avoid computing
    the same fixture twice (each game appears twice in team_match_stats —
    once per side), we identify home/away pairs first, then unpack both
    sides from a single prediction call.
    """
    before = con.execute(
        "SELECT COUNT(*) FROM team_match_predictions_b12 WHERE model_version = ?",
        [MODEL_VERSION],
    ).fetchone()[0]

    # One row per fixture (the 'home' side of team_match_stats)
    fixtures = con.execute("""
        SELECT game_id, team AS home_team, opponent AS away_team, season
        FROM team_match_stats
        WHERE side = 'home'
        ORDER BY game_id
    """).df()

    print(f"Computing B1.2 predictions for {len(fixtures)} fixtures...")

    rows_to_insert = []
    for _, fx in fixtures.iterrows():
        pred = predict_xg(
            con, fx["home_team"], fx["away_team"], fx["season"]
        )
        # Home row
        rows_to_insert.append((
            int(fx["game_id"]), pred.home_team, fx["season"], "home",
            pred.away_team, pred.xg_home,
            pred.home_attack_x_opp_defense, pred.home_side_multiplier,
            MODEL_VERSION,
        ))
        # Away row
        rows_to_insert.append((
            int(fx["game_id"]), pred.away_team, fx["season"], "away",
            pred.home_team, pred.xg_away,
            pred.away_attack_x_opp_defense, pred.away_side_multiplier,
            MODEL_VERSION,
        ))

    con.executemany("""
        INSERT OR IGNORE INTO team_match_predictions_b12
            (game_id, team, season, side, opponent, predicted_xg,
             attack_x_opp_defense, side_multiplier, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)

    after = con.execute(
        "SELECT COUNT(*) FROM team_match_predictions_b12 WHERE model_version = ?",
        [MODEL_VERSION],
    ).fetchone()[0]
    return after - before


def main() -> None:
    print(f"Connecting to {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))

    create_table(con)
    n_inserted = load_predictions(con)
    print(f"\nteam_match_predictions_b12: inserted {n_inserted} new rows "
          f"(model_version={MODEL_VERSION!r})")

    # Spot-check the table
    print("\n=== Sanity check: 5 predictions joined with actuals ===")
    df = con.execute("""
        SELECT
            p.game_id,
            p.team,
            p.opponent,
            p.side,
            ROUND(p.predicted_xg, 3) AS predicted_xg,
            ROUND(tms.xg, 3)         AS actual_xg,
            ROUND(p.predicted_xg - tms.xg, 3) AS residual
        FROM team_match_predictions_b12 p
        JOIN team_match_stats tms
            ON tms.game_id = p.game_id AND tms.team = p.team
        WHERE p.model_version = ?
        ORDER BY p.game_id
        LIMIT 5
    """, [MODEL_VERSION]).df()
    print(df.to_string(index=False))

    # Summary stats
    print("\n=== Summary across all predictions ===")
    summary = con.execute("""
        SELECT
            COUNT(*) AS n_predictions,
            ROUND(AVG(p.predicted_xg), 3) AS mean_predicted,
            ROUND(AVG(tms.xg), 3)         AS mean_actual,
            ROUND(AVG(p.predicted_xg - tms.xg), 3) AS mean_residual
        FROM team_match_predictions_b12 p
        JOIN team_match_stats tms
            ON tms.game_id = p.game_id AND tms.team = p.team
        WHERE p.model_version = ?
    """, [MODEL_VERSION]).df()
    print(summary.to_string(index=False))

    con.close()


if __name__ == "__main__":
    main()