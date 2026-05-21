"""
V1.02 modeling — STEP 5a: expand formation library from 4 to 10.

WHAT THIS DOES
    Adds 6 new formations (and their 11-slot definitions) to the existing
    formations + formation_slots tables. Uses INSERT OR IGNORE so re-runs
    are safe and the existing 4 formations (4-3-3, 4-2-3-1, 4-4-2, 4-1-4-1)
    are untouched.

THE 6 NEW FORMATIONS
    4-5-1     Back-4, defensive setup, 1 striker
    3-4-3     Back-3 attacking, 2 wing-backs, front 3
    3-5-2     Back-3 with 5 mids, 2 strikers
    3-4-2-1   Back-3 with two #10s behind a lone striker
    5-3-2     Very defensive back-3 (wing-backs sit deep), 2 strikers
    5-4-1     Park-the-bus, lone striker, 4-man midfield

WING-BACK CLASSIFICATION (S8 DECISION)
    In all back-3 / back-5 formations, wing-backs (LWB/RWB) are classed
    as DEF (per the `positions` table). This is documented as a known
    limitation — true positional class depends on play-style, which
    arrives in V1.03+. For now, DEF is the safe default for line
    integrity.

FRONT-3 INVERTED-WINGER NUANCE
    3-4-2-1's "2" between the midfield and striker is traditionally two
    inside-forwards or attacking midfielders. Our positions vocabulary
    has RW/LW (FWD class) and CAM (MID class) but no dedicated "inside
    forward" code. Using RW + CAM + LW as the slot codes — class is
    FWD+MID+FWD, which approximates the structural role. Documented
    as a limitation.

HOW TO RUN
    From the repo root:
        uv run python src/load/expand_formations_v102.py
    (Note: lives in src/load/ because it's a one-shot schema seed,
    matching the original v102_scenario_schema.py convention.)
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# 6 new formations + their 11 slots each.
# Slot order is GK first, then back-to-front, left-to-right.
NEW_FORMATIONS = {
    "4-5-1":   ["GK", "RB",  "RCB", "LCB", "LB", "RM",  "RCM", "CM",  "LCM", "LM",  "ST"],
    "3-4-3":   ["GK", "RCB", "CB",  "LCB", "RWB", "RCM", "LCM", "LWB", "RW",  "ST",  "LW"],
    "3-5-2":   ["GK", "RCB", "CB",  "LCB", "RWB", "RCM", "CM",  "LCM", "LWB", "ST",  "ST"],
    "3-4-2-1": ["GK", "RCB", "CB",  "LCB", "RWB", "RCM", "LCM", "LWB", "RW",  "CAM", "LW"],
    "5-3-2":   ["GK", "RB",  "RCB", "CB",  "LCB", "LB",  "RCM", "CM",  "LCM", "ST",  "ST"],
    "5-4-1":   ["GK", "RB",  "RCB", "CB",  "LCB", "LB",  "RM",  "RCM", "LCM", "LM",  "ST"],
}


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Sanity: the tables must already exist.
        existing_tables = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for required in ("formations", "formation_slots", "positions"):
            if required not in existing_tables:
                raise SystemExit(
                    f"Required table '{required}' missing. Run "
                    f"src/load/v102_scenario_schema.py first."
                )

        # 2. Sanity: every position_code we reference must already exist
        # in the positions table. The S5 vocabulary includes RWB/LWB/CB
        # for back-3 work, so this should pass — but verify.
        used_codes = set()
        for codes in NEW_FORMATIONS.values():
            used_codes.update(codes)
        existing_codes = {
            r[0] for r in con.execute(
                "SELECT position_code FROM positions"
            ).fetchall()
        }
        missing_codes = used_codes - existing_codes
        if missing_codes:
            raise SystemExit(
                f"Position codes missing from `positions` table: "
                f"{missing_codes}. Cannot seed."
            )

        # 3. Insert formations + slots in a transaction.
        print(f"Seeding {len(NEW_FORMATIONS)} new formations...")
        con.execute("BEGIN TRANSACTION")
        try:
            # 3a. Formations table — one row per new formation.
            con.executemany(
                "INSERT OR IGNORE INTO formations VALUES (?)",
                [(f,) for f in NEW_FORMATIONS],
            )

            # 3b. formation_slots — 11 rows per new formation.
            slot_rows = []
            for formation, codes in NEW_FORMATIONS.items():
                assert len(codes) == 11, (
                    f"{formation} has {len(codes)} slots, expected 11"
                )
                for slot_no, code in enumerate(codes, start=1):
                    slot_rows.append((formation, slot_no, code))
            con.executemany(
                "INSERT OR IGNORE INTO formation_slots VALUES (?, ?, ?)",
                slot_rows,
            )

            con.execute("COMMIT")
            print(f"COMMITTED. Inserted {len(NEW_FORMATIONS)} formations and "
                  f"{len(slot_rows)} slot rows.")
        except Exception:
            print("!!! Error during seed, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 4. Verify — total counts and class distribution per formation.
        print("\n--- All formations in DB ---")
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
        print(f"{'formation':<10} {'GK':>3} {'DEF':>4} {'MID':>4} {'FWD':>4}")
        for formation, gk, dfn, mid, fwd in rows:
            print(f"{formation:<10} {gk:>3} {dfn:>4} {mid:>4} {fwd:>4}")

        total_formations = con.execute(
            "SELECT COUNT(*) FROM formations"
        ).fetchone()[0]
        total_slots = con.execute(
            "SELECT COUNT(*) FROM formation_slots"
        ).fetchone()[0]
        print(f"\nTotals: {total_formations} formations, {total_slots} "
              f"slot rows (expected {total_formations * 11}).")
    finally:
        con.close()


if __name__ == "__main__":
    main()