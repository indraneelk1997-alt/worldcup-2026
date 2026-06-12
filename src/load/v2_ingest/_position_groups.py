"""
_position_groups.py (S27) — map each source's per-match position vocab to the
coarse percentile groups {GK, DEF, MID, FWD}.

Three vocabularies (observed S27): Understat codes (AMR/DMC/DC…), FBref codes
(CAM/CB/DM…), StatsBomb strings ("Right Wing", "Center Attacking Midfield"…).

KEY RULE (maintainer call, S27): **attacking mids AND wingers → FWD** (CAM/AMC,
AMR/AML, wings). Rationale: the MID group is dominated by single/double-pivot
holders; a #10's attacking output (Bruno) is winger-like, so grouping it into
MID skews the midfield baseline. Backs + wing-backs → DEF.
"""
from __future__ import annotations

# Understat effective_position codes
UNDERSTAT = {
    "GK": "GK",
    "DC": "DEF", "DR": "DEF", "DL": "DEF",
    "DMC": "MID", "DMR": "MID", "DML": "MID",
    "MC": "MID", "MR": "MID", "ML": "MID",
    "AMC": "FWD", "AMR": "FWD", "AML": "FWD",
    "FW": "FWD", "FWR": "FWD", "FWL": "FWD",
    "Sub": None,
}

# FBref effective_position codes (incl. defensive extras for safety)
FBREF = {
    "GK": "GK",
    "CB": "DEF", "LCB": "DEF", "RCB": "DEF", "LB": "DEF", "RB": "DEF",
    "LWB": "DEF", "RWB": "DEF", "DF": "DEF",
    "DM": "MID", "CM": "MID", "LCM": "MID", "RCM": "MID",
    "LM": "MID", "RM": "MID", "MF": "MID",
    "CAM": "FWD", "LAM": "FWD", "RAM": "FWD",
    "FW": "FWD", "LW": "FWD", "RW": "FWD",
}


def statsbomb(s: str | None) -> str | None:
    """StatsBomb full-string positions → coarse. Order matters: 'Back' before
    'Wing' so wing-backs land DEF; 'Attacking Midfield' before generic Midfield."""
    if not s:
        return None
    if s == "Goalkeeper":
        return "GK"
    if "Back" in s:                      # Center/Left/Right Back, Wing Back
        return "DEF"
    if "Attacking Midfield" in s:        # Center/Left/Right Attacking Midfield
        return "FWD"
    if "Wing" in s:                      # Left/Right Wing (not Wing Back)
        return "FWD"
    if "Forward" in s:                   # Center / L/R Center Forward
        return "FWD"
    if "Midfield" in s:                  # Defensive/Center/Left/Right Midfield
        return "MID"
    return None                          # Substitute / unknown


def coarse(source: str, code: str | None) -> str | None:
    if source == "understat":
        return UNDERSTAT.get(code)
    if source == "fbref":
        return FBREF.get(code)
    if source == "statsbomb":
        return statsbomb(code)
    return None
