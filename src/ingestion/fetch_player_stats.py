"""
Fetch player season stats from FBref.

V1.01: Premier League only, last completed season (2024-2025).
We'll expand to more leagues in future versions.
"""

import logging
from pathlib import Path

import soccerdata as sd

# Set up logging so we can see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Where to save the raw data
# This file is at: src/ingestion/fetch_player_stats.py
# So the project root is two folders up: ../../
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


def fetch_premier_league(season: str = "2024-2025"):
    """Fetch standard player stats for one Premier League season."""
    logger.info(f"Fetching Premier League stats for {season}")

    fbref = sd.FBref(leagues="ENG-Premier League", seasons=season)
    df = fbref.read_player_season_stats(stat_type="standard")

    logger.info(f"Got {len(df)} player rows")

    # Make sure the output folder exists
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Save as CSV (human-readable, easy to inspect)
    output_path = RAW_DATA_DIR / f"epl_player_stats_{season}.csv"
    df.to_csv(output_path)
    logger.info(f"Saved to {output_path}")


if __name__ == "__main__":
    fetch_premier_league()