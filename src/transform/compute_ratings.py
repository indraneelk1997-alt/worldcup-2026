"""
Compute V1.01 player ratings from raw Understat data.

V1.01 rating formula:
    rating_per_90 = (np_xg + xa) / (minutes / 90)

Where:
    - np_xg = non-penalty expected goals (Understat)
    - xa = expected assists (Understat)

Players with fewer than 450 minutes (5 full matches) are excluded
to avoid small-sample noise.

Reads from:  data/raw/epl_player_stats_understat_<season>.csv
Writes to:   data/processed/player_ratings_v101_<season>.csv
"""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

# V1.01 parameters
MIN_MINUTES = 450


def compute_ratings(season: str = "2024-2025") -> pd.DataFrame:
    """Load raw data, compute ratings, save to processed folder."""
    # Load
    raw_path = RAW_DATA_DIR / f"epl_player_stats_understat_{season}.csv"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Raw data not found: {raw_path}\n"
            f"Run src/ingestion/fetch_player_stats.py first."
        )

    logger.info(f"Loading raw data from {raw_path}")
    df = pd.read_csv(raw_path, index_col=0)
    logger.info(f"Loaded {len(df)} player rows")

    # Filter
    qualified = df[df["minutes"] >= MIN_MINUTES].copy()
    logger.info(
        f"Filtered to {len(qualified)} players with >= {MIN_MINUTES} minutes "
        f"(excluded {len(df) - len(qualified)})"
    )

    # Compute rating
    qualified["rating_per_90"] = (
        (qualified["np_xg"] + qualified["xa"]) / (qualified["minutes"] / 90.0)
    )

    # Sort and select columns we care about
    qualified = qualified.sort_values("rating_per_90", ascending=False)
    output_cols = [
        "player",
        "team",
        "position",
        "matches",
        "minutes",
        "goals",
        "assists",
        "np_xg",
        "xa",
        "rating_per_90",
    ]
    result = qualified[output_cols]

    # Save
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DATA_DIR / f"player_ratings_v101_{season}.csv"
    result.to_csv(output_path, index=False)
    logger.info(f"Saved {len(result)} ratings to {output_path}")

    return result


if __name__ == "__main__":
    df = compute_ratings()
    # Show top 10 as a sanity check
    print("\nTop 10 players by rating:")
    print(df.head(10).to_string(index=False))