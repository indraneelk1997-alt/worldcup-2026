"""
V1.02 schema refactor — PART 1 of 2: scenario + formation tables.

WHAT THIS DOES
    Creates five NEW tables and seeds the three reference tables among them.
    It is a pure ADD: no existing table (players, fixtures, fixture_lineups,
    predictions, player_season_stats) is touched, so running this cannot
    destroy data. Safe to re-run — every write is CREATE TABLE IF NOT EXISTS
    or INSERT OR IGNORE.

    New tables:
      formations        reference — the set of valid formation labels
      positions         reference — canonical position vocabulary
      formation_slots   reference — the 11 slots that compose each formation
      lineup_scenarios  data      — one row per what-if lineup set for a fixture
      scenario_teams    data      — one row per side (home/away) of a scenario

WHAT PART 2 WILL DO (separate session step — NOT here)
    Refactor fixture_lineups.fixture_id -> (scenario_id, side, slot_no) and
    predictions.fixture_id -> scenario_id, then migrate the existing trial
    rows. That part is destructive (drops + recreates), so it gets its own
    careful step.

HOW TO RUN
    From the repo root:
        uv run python src/load/v102_scenario_schema.py
    It expects the DuckDB file at data/processed/worldcup.duckdb.

FOREIGN-KEY TYPE NOTE (resolved in this version)
    lineup_scenarios.fixture_id is VARCHAR to match fixtures.fixture_id
    (Understat fixture IDs are string identifiers from the source, stored
    as VARCHAR). DuckDB requires foreign-key column types to match exactly,
    so this matters. Verified via DESCRIBE fixtures before writing.
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# --- seed data -------------------------------------------------------------

# Only 4-defender formations are seeded for V1.02. Back-3 / wing-back systems
# (3-5-2, 3-4-3, 5-3-2) are deferred to V1.03: classifying a wing-back as a
# defender vs a midfielder is really a play-style question, and V1.03 is where
# play styles arrive. The `positions` vocabulary below already includes the
# wing-back / centre codes, so adding those formations later is just INSERTs.
FORMATIONS = ["4-3-3", "4-2-3-1", "4-4-2", "4-1-4-1"]

# Canonical position vocabulary — "moderate" granularity (18 codes).
# Fine-grained codes (RWB variants, RF/LF, etc.) come in V1.03/V1.04.
# position_class drives V1.02 position weighting (GK/DEF/MID/FWD).
# flank (L/C/R) is groundwork for V1.04 zonal-advantage analysis.
POSITIONS = [
    # position_code, position_class, flank
    ("GK",  "GK",  "C"),
    ("RB",  "DEF", "R"),
    ("RWB", "DEF", "R"),   # used by back-3 formations in V1.03
    ("RCB", "DEF", "R"),
    ("CB",  "DEF", "C"),   # used by back-3 formations in V1.03
    ("LCB", "DEF", "L"),
    ("LWB", "DEF", "L"),   # used by back-3 formations in V1.03
    ("LB",  "DEF", "L"),
    ("DM",  "MID", "C"),
    ("RCM", "MID", "R"),
    ("CM",  "MID", "C"),   # unused by the 4 seeded formations; kept for V1.03
    ("LCM", "MID", "L"),
    ("RM",  "MID", "R"),
    ("LM",  "MID", "L"),
    ("CAM", "MID", "C"),
    ("RW",  "FWD", "R"),
    ("LW",  "FWD", "L"),
    ("ST",  "FWD", "C"),
]

# slot_no 1..11 -> position_code, for each formation.
# Design decision worth noting: a 4-3-3's front three are FORWARDS
# (RW/ST/LW), but a 4-2-3-1's attacking three are MIDFIELDERS (RM/CAM/LM).
# That difference in class is exactly what separates the two shapes, and it
# falls out automatically once you join formation_slots -> positions.
FORMATION_SLOTS = {
    "4-3-3":   ["GK", "RB", "RCB", "LCB", "LB", "DM", "RCM", "LCM", "RW", "ST", "LW"],
    "4-2-3-1": ["GK", "RB", "RCB", "LCB", "LB", "DM", "DM",  "RM",  "CAM", "LM", "ST"],
    "4-4-2":   ["GK", "RB", "RCB", "LCB", "LB", "RM", "RCM", "LCM", "LM",  "ST", "ST"],
    "4-1-4-1": ["GK", "RB", "RCB", "LCB", "LB", "DM", "RM",  "RCM", "LCM", "LM", "ST"],
}

# --- DDL -------------------------------------------------------------------
# One statement per list item. Order matters: a table that REFERENCES another
# must be created AFTER the table it points to (parent before child).
DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS formations (
        formation VARCHAR PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        position_code  VARCHAR PRIMARY KEY,
        position_class VARCHAR NOT NULL CHECK (position_class IN ('GK','DEF','MID','FWD')),
        flank          VARCHAR NOT NULL CHECK (flank IN ('L','C','R'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS formation_slots (
        formation     VARCHAR NOT NULL REFERENCES formations(formation),
        slot_no       INTEGER NOT NULL CHECK (slot_no BETWEEN 1 AND 11),
        position_code VARCHAR NOT NULL REFERENCES positions(position_code),
        PRIMARY KEY (formation, slot_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lineup_scenarios (
        scenario_id   INTEGER PRIMARY KEY,
        fixture_id    VARCHAR NOT NULL REFERENCES fixtures(fixture_id),
        scenario_type VARCHAR NOT NULL,   -- intended values: auto_top11 | predicted | actual | manual
        label         VARCHAR,            -- human-readable, e.g. "Palace 4-3-3 Sarr"
        created_at    TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenario_teams (
        scenario_id INTEGER NOT NULL REFERENCES lineup_scenarios(scenario_id),
        side        VARCHAR NOT NULL CHECK (side IN ('home','away')),
        team        VARCHAR NOT NULL,     -- matches player_season_stats.team (no teams table yet)
        formation   VARCHAR NOT NULL REFERENCES formations(formation),
        PRIMARY KEY (scenario_id, side)
    )
    """,
]


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    # Wrap in try/finally: a DuckDB connection holds a file lock, and we want
    # it released even if something below raises.
    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Create the five new tables (parents before children).
        for stmt in DDL_STATEMENTS:
            con.execute(stmt)

        # 2. Seed formations.
        con.executemany(
            "INSERT OR IGNORE INTO formations VALUES (?)",
            [(f,) for f in FORMATIONS],
        )

        # 3. Seed positions.
        con.executemany(
            "INSERT OR IGNORE INTO positions VALUES (?, ?, ?)",
            POSITIONS,
        )

        # 4. Seed formation_slots, expanded from the dict above.
        slot_rows = []
        for formation, codes in FORMATION_SLOTS.items():
            assert len(codes) == 11, (
                f"{formation} must have exactly 11 slots, got {len(codes)}"
            )
            for slot_no, code in enumerate(codes, start=1):
                slot_rows.append((formation, slot_no, code))
        con.executemany(
            "INSERT OR IGNORE INTO formation_slots VALUES (?, ?, ?)",
            slot_rows,
        )

        # 5. Verify — row counts for all five tables.
        print("Row counts after migration:")
        for tbl in ("formations", "positions", "formation_slots",
                    "lineup_scenarios", "scenario_teams"):
            n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl:<18} {n:>4}")

        # 6. Sanity check — every formation must have exactly 11 slots.
        bad = con.execute(
            """
            SELECT formation, COUNT(*) AS slots
            FROM formation_slots
            GROUP BY formation
            HAVING COUNT(*) <> 11
            """
        ).fetchall()
        if bad:
            print("  WARNING — formations without 11 slots:", bad)
        else:
            print("  OK — every seeded formation has exactly 11 slots")

        # 7. Show each formation's class distribution. This joins
        #    formation_slots -> positions, which is the exact path the model
        #    will use to find a player's position class for position weighting.
        print("\nFormation class distribution (GK / DEF / MID / FWD):")
        rows = con.execute(
            """
            SELECT fs.formation,
                   SUM(p.position_class = 'GK')  AS gk,
                   SUM(p.position_class = 'DEF') AS def,
                   SUM(p.position_class = 'MID') AS mid,
                   SUM(p.position_class = 'FWD') AS fwd
            FROM formation_slots fs
            JOIN positions p ON p.position_code = fs.position_code
            GROUP BY fs.formation
            ORDER BY fs.formation
            """
        ).fetchall()
        for formation, gk, dfn, mid, fwd in rows:
            print(f"  {formation:<9} {gk}-{dfn}-{mid}-{fwd}")
    finally:
        con.close()


if __name__ == "__main__":
    main()