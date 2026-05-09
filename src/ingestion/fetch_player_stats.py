"""
Fetch player season stats from Understat.

V1.01: Premier League only, last completed season (2024-2025).
We use Understat (not FBref) because it provides npxG and xA natively
and avoids FBref's Cloudflare bot protection issues.

Coverage: top-5 European leagues. UCL/UEL not available on Understat
(deferred to V1.02+).
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


def fetch_premier_league(season: str = "2024-2025"):
    """Fetch player season stats from Understat for one Premier League season."""
    logger.info(f"Fetching Premier League stats for {season} from Understat")

    understat = sd.Understat(leagues="ENG-Premier League", seasons=season)
    df = understat.read_player_season_stats()

    logger.info(f"Got {len(df)} player rows")

    # Make sure the output folder exists
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Save as CSV (human-readable, easy to inspect)
    output_path = RAW_DATA_DIR / f"epl_player_stats_understat_{season}.csv"
    df.to_csv(output_path)
    logger.info(f"Saved to {output_path}")


if __name__ == "__main__":
    fetch_premier_league()