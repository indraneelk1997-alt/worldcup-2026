"""
V1.03 modeling — STEP 5 (A6): fine-grained position upgrade.

WHAT THIS DOES
    Replaces V1.02's coarse 4-class position vocabulary (GK/DEF/MID/FWD)
    with V1.03's 6-tier classification + 20-code position vocabulary,
    derived from per-match data with empirical validation.

THE EMPIRICAL DECISIONS (S11 validation queries confirmed)
    1. DML/DMR are wing-backs in back-3 formations (97% of cases).
       Map: DML -> LWB, DMR -> RWB. Class: DEF.
    2. DMC is single-pivot DM, MC is box-to-box CM. Roles are mostly
       distinct (specialists with some rotation overlap).
       Map: DMC -> DM (DEF-MID), MC -> CM (CENTRAL-MID).
    3. MR/ML are 4-4-2 wide mids (94% of cases). Not as defensive as
       wing-backs, not as attacking as AMR/AML. Class: CENTRAL-MID.
    4. AMR/AML are inverted attacking wingers (Salah, Saka style).
       They are NOT equivalent to RW/LW — they play deeper. Class:
       ATT-MID. Adds 2 new codes RAM/LAM to positions vocabulary.

THE 6-TIER CLASS STRUCTURE (replaces V1.02's 4-class)
    GK           : GK
    DEF          : CB, LCB, RCB, RB, LB, LWB, RWB
    DEF-MID      : DM
    CENTRAL-MID  : CM, LCM, RCM, RM, LM
    ATT-MID      : CAM, RAM (NEW), LAM (NEW)
    FWD          : ST, RW, LW

PRIMARY POSITION DERIVATION (per player, season, team)
    1. Filter to ≥45-min matches (consistency with A3 shrinkage)
    2. Sum minutes by effective_position (uses A1's policy-C backfill
       for Sub rows)
    3. Map Understat code -> our code
    4. The code with most minutes is primary (priority=1)
    5. Subsequent codes (if their summed minutes > 0) get priority 2, 3, ...
    6. Position class is derived from primary code.

FALLBACK CHAIN FOR ZERO-MATCH PLAYERS
    A player with no ≥45-min matches in a season (e.g., only Sub
    appearances) falls back to:
      1. Map V1.02 position_class to default code:
         GK -> GK, DEF -> CB, MID -> CM, FWD -> ST
      2. Source = 'fallback' (vs 'per_match' for the normal case)

NEW ARTIFACTS
    1. positions table: +2 rows (RAM, LAM)
    2. positions table: +1 column position_class_v103 (the 6-tier class)
    3. player_positions_v103 table: parallel to player_positions but
       with new 20-code vocab + position_source column
    4. player_season_stats: +2 columns
         primary_position_code_v103   (e.g., 'RAM' for Salah)
         primary_position_class_v103  (e.g., 'ATT-MID' for Salah)

V1.02 BACKWARD COMPATIBILITY
    player_positions table (4-class), position_class column (4-class),
    and best_xi (uses 4-class) are ALL UNTOUCHED. V1.02 simulator code
    continues to function. The V1.03 simulator (to be built later) will
    use the new vocabulary.

HOW TO RUN
    From the repo root:
        uv run python src/model/fine_grained_position.py
"""

import duckdb
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

MIN_MINUTES_PER_MATCH = 45    # consistent with A3 shrinkage filter

# Understat per-match position -> (our position_code, our 6-tier class)
UNDERSTAT_TO_OURS = {
    "GK":  ("GK",  "GK"),
    "DC":  ("CB",  "DEF"),
    "DR":  ("RB",  "DEF"),
    "DL":  ("LB",  "DEF"),
    "DMR": ("RWB", "DEF"),       # empirically validated wing-back
    "DML": ("LWB", "DEF"),       # empirically validated wing-back
    "DMC": ("DM",  "DEF-MID"),   # single-pivot DM
    "MC":  ("CM",  "CENTRAL-MID"),
    "MR":  ("RM",  "CENTRAL-MID"),  # 4-4-2 wide mid
    "ML":  ("LM",  "CENTRAL-MID"),
    "AMC": ("CAM", "ATT-MID"),
    "AMR": ("RAM", "ATT-MID"),   # NEW code — inverted right winger
    "AML": ("LAM", "ATT-MID"),   # NEW code — inverted left winger
    "FW":  ("ST",  "FWD"),
    "FWR": ("RW",  "FWD"),
    "FWL": ("LW",  "FWD"),
    # 'Sub' is handled separately via effective_position
}

# Fallback chain — V1.02 position_class -> default (code, class)
V102_CLASS_FALLBACK = {
    "GK":  ("GK", "GK"),
    "DEF": ("CB", "DEF"),
    "MID": ("CM", "CENTRAL-MID"),
    "FWD": ("ST", "FWD"),
}

# Existing 18 codes that already have position_class in V1.02's
# positions table. We need to add position_class_v103 (6-tier) to all
# of them + add 2 new rows (RAM, LAM).
# Mapping uses the same scheme as UNDERSTAT_TO_OURS above (consistent).
CODE_TO_V103_CLASS = {
    "GK":  "GK",
    "CB":  "DEF",  "LCB": "DEF",  "RCB": "DEF",
    "RB":  "DEF",  "LB":  "DEF",
    "RWB": "DEF",  "LWB": "DEF",
    "DM":  "DEF-MID",
    "CM":  "CENTRAL-MID", "LCM": "CENTRAL-MID", "RCM": "CENTRAL-MID",
    "RM":  "CENTRAL-MID", "LM":  "CENTRAL-MID",
    "CAM": "ATT-MID",
    "RAM": "ATT-MID",  # NEW
    "LAM": "ATT-MID",  # NEW
    "ST":  "FWD",
    "RW":  "FWD",  "LW":  "FWD",
}


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Verify prerequisites.
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for required in ("positions", "players", "player_season_stats",
                         "player_match_stats", "player_positions"):
            if required not in existing:
                raise SystemExit(
                    f"Required table '{required}' missing."
                )

        print("=== STEP 1: extend positions table ===")
        # 1a. Add position_class_v103 column if not present.
        pos_cols = {
            r[0] for r in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'positions'
                """
            ).fetchall()
        }
        if "position_class_v103" not in pos_cols:
            con.execute(
                "ALTER TABLE positions ADD COLUMN position_class_v103 VARCHAR"
            )
            print("  Added column positions.position_class_v103")

        # 1b. Insert RAM and LAM if not present.
        existing_codes = {
            r[0] for r in con.execute(
                "SELECT position_code FROM positions"
            ).fetchall()
        }
        new_position_rows = []
        for new_code, new_flank in (("RAM", "R"), ("LAM", "L")):
            if new_code not in existing_codes:
                # V1.02's positions table columns:
                # position_code, position_class, flank (all NOT NULL).
                # We default position_class (V1.02 4-tier) to 'MID' so
                # V1.02 code that filters on it still works sensibly.
                # flank is 'R' for right-attacking-mid, 'L' for left.
                new_position_rows.append((new_code, "MID", new_flank))
        if new_position_rows:
            con.execute("BEGIN TRANSACTION")
            try:
                con.executemany(
                    "INSERT INTO positions "
                    "(position_code, position_class, flank) "
                    "VALUES (?, ?, ?)",
                    new_position_rows,
                )
                con.execute("COMMIT")
                print(f"  Inserted {len(new_position_rows)} new position "
                      f"rows: {[r[0] for r in new_position_rows]}")
            except Exception:
                con.execute("ROLLBACK")
                raise

        # 1c. Populate position_class_v103 for all rows.
        # Idempotent — UPDATE based on the mapping.
        con.execute("BEGIN TRANSACTION")
        try:
            for code, v103_class in CODE_TO_V103_CLASS.items():
                con.execute(
                    "UPDATE positions SET position_class_v103 = ? "
                    "WHERE position_code = ?",
                    [v103_class, code],
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        # Verify all positions have position_class_v103 set.
        nulls = con.execute(
            "SELECT COUNT(*) FROM positions WHERE position_class_v103 IS NULL"
        ).fetchone()[0]
        if nulls > 0:
            unmapped = con.execute(
                "SELECT position_code FROM positions "
                "WHERE position_class_v103 IS NULL"
            ).fetchall()
            raise SystemExit(
                f"FAIL: {nulls} positions rows lack position_class_v103: "
                f"{[r[0] for r in unmapped]}. Update CODE_TO_V103_CLASS."
            )

        print(f"  positions table: "
              f"{con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]} "
              f"rows, all have V1.02 class + V1.03 class")

        # 2. Create player_positions_v103 table if not present.
        print("\n=== STEP 2: create player_positions_v103 table ===")
        if "player_positions_v103" not in existing:
            con.execute("""
                CREATE TABLE player_positions_v103 (
                    player_id       INTEGER NOT NULL REFERENCES players(player_id),
                    season          VARCHAR NOT NULL,
                    team            VARCHAR NOT NULL,
                    position_code   VARCHAR NOT NULL REFERENCES positions(position_code),
                    position_class  VARCHAR NOT NULL,
                    minutes_in_role INTEGER NOT NULL,
                    n_matches       INTEGER NOT NULL,
                    priority        INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 10),
                    position_source VARCHAR NOT NULL CHECK (position_source IN ('per_match', 'fallback')),
                    PRIMARY KEY (player_id, season, team, position_code)
                )
            """)
            print("  Created player_positions_v103")
        else:
            print("  player_positions_v103 already exists")

        # 3. Add primary_position_code_v103 and primary_position_class_v103
        # columns to player_season_stats.
        print("\n=== STEP 3: add columns to player_season_stats ===")
        pss_cols = {
            r[0] for r in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'player_season_stats'
                """
            ).fetchall()
        }
        for new_col in ("primary_position_code_v103",
                        "primary_position_class_v103"):
            if new_col not in pss_cols:
                con.execute(
                    f"ALTER TABLE player_season_stats "
                    f"ADD COLUMN {new_col} VARCHAR"
                )
                print(f"  Added {new_col}")

        # 4. Build the per-player position distribution from per-match data.
        print("\n=== STEP 4: derive primary positions from per-match data ===")
        print(f"Filter: ≥{MIN_MINUTES_PER_MATCH}-min matches, "
              f"using effective_position (incl. policy-C backfilled Subs).")

        # Aggregate minutes by (player, season, team, our_code).
        # Use effective_position to honor the policy-C backfill from A1.
        # Map Understat code -> our code via UNDERSTAT_TO_OURS.
        raw_rows = con.execute(
            """
            SELECT
                player_id, season, team, effective_position,
                SUM(minutes) AS total_min,
                COUNT(*)     AS n_matches
            FROM player_match_stats
            WHERE minutes >= ?
              AND effective_position != 'Sub'
            GROUP BY player_id, season, team, effective_position
            """,
            [MIN_MINUTES_PER_MATCH],
        ).fetchall()
        print(f"  Aggregated {len(raw_rows)} (player, season, team, "
              f"position) rows from per-match data.")

        # Map Understat codes -> ours and accumulate.
        # Some Understat codes may map to the same our_code (none in current
        # mapping, but defensive).
        from collections import defaultdict
        aggregated = defaultdict(lambda: {"minutes": 0, "matches": 0})
        unmapped_codes = set()
        for pid, season, team, pos, mins, n in raw_rows:
            mapping = UNDERSTAT_TO_OURS.get(pos)
            if mapping is None:
                unmapped_codes.add(pos)
                continue
            our_code, our_class = mapping
            key = (pid, season, team, our_code, our_class)
            aggregated[key]["minutes"] += mins
            aggregated[key]["matches"] += n

        if unmapped_codes:
            raise SystemExit(
                f"FAIL: per-match data has unmapped position codes: "
                f"{unmapped_codes}. Update UNDERSTAT_TO_OURS."
            )
        print(f"  Mapped to {len(aggregated)} unique (player, season, team, "
              f"our_code) combos.")

        # 5. Within each (player, season, team), assign priority by minutes
        # descending. Same shape as player_positions table.
        # Group aggregated by (player, season, team), sort by minutes desc.
        grouped = defaultdict(list)
        for (pid, season, team, code, cls), d in aggregated.items():
            grouped[(pid, season, team)].append((
                code, cls, d["minutes"], d["matches"]
            ))

        pp_v103_rows = []  # rows for player_positions_v103
        primary_lookup = {}  # (pid, season, team) -> (primary_code, primary_class)
        for (pid, season, team), entries in grouped.items():
            entries.sort(key=lambda e: -e[2])  # by minutes desc
            for priority, (code, cls, mins, n) in enumerate(entries,
                                                            start=1):
                pp_v103_rows.append((
                    pid, season, team, code, cls, mins, n, priority,
                    "per_match",
                ))
            primary_lookup[(pid, season, team)] = (
                entries[0][0], entries[0][1]
            )

        print(f"  Built {len(pp_v103_rows)} player_positions_v103 rows "
              f"({len(primary_lookup)} unique (player, season, team) "
              f"combos with per_match data).")

        # 6. Identify player_season_stats rows that need fallback (no
        # qualifying per-match data).
        pss_rows = con.execute(
            """
            SELECT player_id, season, team, position_class
            FROM player_season_stats
            """
        ).fetchall()

        fallback_count = 0
        for pid, season, team, v102_class in pss_rows:
            key = (pid, season, team)
            if key in primary_lookup:
                continue
            # Fallback chain
            fallback = V102_CLASS_FALLBACK.get(v102_class)
            if fallback is None:
                # Shouldn't happen; v102_class should be one of 4 known
                # values. Defensive default to CM/CENTRAL-MID.
                fallback = ("CM", "CENTRAL-MID")
            code, cls = fallback
            primary_lookup[key] = (code, cls)
            pp_v103_rows.append((
                pid, season, team, code, cls, 0, 0, 1, "fallback",
            ))
            fallback_count += 1

        print(f"  Added {fallback_count} fallback rows (players with no "
              f"≥{MIN_MINUTES_PER_MATCH}-min matches in that season).")

        # 7. Write everything in a transaction.
        # Idempotency: wipe player_positions_v103 and the two new pss
        # columns by season, then re-insert.
        print("\n=== STEP 5: write to DB ===")
        con.execute("BEGIN TRANSACTION")
        try:
            seasons = sorted({r[1] for r in pp_v103_rows})
            for season in seasons:
                con.execute(
                    "DELETE FROM player_positions_v103 WHERE season = ?",
                    [season],
                )

            con.executemany(
                """
                INSERT INTO player_positions_v103
                    (player_id, season, team, position_code,
                     position_class, minutes_in_role, n_matches,
                     priority, position_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pp_v103_rows,
            )

            # Update primary_position_code_v103 + primary_position_class_v103
            # on player_season_stats from primary_lookup.
            update_rows = [
                (code, cls, pid, season, team)
                for (pid, season, team), (code, cls) in primary_lookup.items()
            ]
            con.executemany(
                """
                UPDATE player_season_stats
                SET primary_position_code_v103 = ?,
                    primary_position_class_v103 = ?
                WHERE player_id = ? AND season = ? AND team = ?
                """,
                update_rows,
            )

            # Verify.
            pp_v103_count = con.execute(
                "SELECT COUNT(*) FROM player_positions_v103"
            ).fetchone()[0]
            pss_null_code = con.execute(
                "SELECT COUNT(*) FROM player_season_stats "
                "WHERE primary_position_code_v103 IS NULL"
            ).fetchone()[0]
            print(f"  player_positions_v103: {pp_v103_count} rows")
            print(f"  player_season_stats with NULL "
                  f"primary_position_code_v103: {pss_null_code}")
            if pss_null_code > 0:
                raise SystemExit(
                    "FAIL: some player_season_stats rows still have NULL "
                    "primary_position_code_v103. Rolling back."
                )

            con.execute("COMMIT")
            print("  COMMITTED.")
        except Exception:
            print("!!! Rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 8. Sanity outputs.
        print("\n=== STEP 6: sanity outputs ===")

        # Distribution of primary position classes V1.02 vs V1.03.
        print("\n--- V1.02 (4-tier) vs V1.03 (6-tier) class distribution "
              "(2025-2026) ---")
        print("V1.02:")
        for r in con.execute(
            """
            SELECT position_class, COUNT(*) AS n
            FROM player_season_stats
            WHERE season = '2025-2026'
            GROUP BY position_class
            ORDER BY n DESC
            """
        ).fetchall():
            print(f"  {r[0]:<14} {r[1]:>4}")
        print("V1.03:")
        for r in con.execute(
            """
            SELECT primary_position_class_v103, COUNT(*) AS n
            FROM player_season_stats
            WHERE season = '2025-2026'
            GROUP BY primary_position_class_v103
            ORDER BY n DESC
            """
        ).fetchall():
            print(f"  {r[0]:<14} {r[1]:>4}")

        # Distribution of primary position codes (V1.03).
        print("\n--- V1.03 primary code distribution (2025-2026) ---")
        for r in con.execute(
            """
            SELECT primary_position_code_v103, COUNT(*) AS n
            FROM player_season_stats
            WHERE season = '2025-2026'
            GROUP BY primary_position_code_v103
            ORDER BY n DESC
            """
        ).fetchall():
            print(f"  {r[0]:<6} {r[1]:>4}")

        # Players whose V1.02 class != V1.03 class — the reclassification cases.
        print("\n--- Players reclassified V1.02 -> V1.03 (2025-2026, "
              "top 15 by minutes) ---")
        for r in con.execute(
            """
            SELECT p.player_name, pss.team, pss.minutes,
                   pss.position_class AS v102_class,
                   pss.primary_position_code_v103 AS v103_code,
                   pss.primary_position_class_v103 AS v103_class
            FROM player_season_stats pss
            JOIN players p USING (player_id)
            WHERE pss.season = '2025-2026'
              AND (
                  (pss.position_class = 'FWD' AND pss.primary_position_class_v103 = 'ATT-MID')
                  OR (pss.position_class = 'FWD' AND pss.primary_position_class_v103 = 'CENTRAL-MID')
                  OR (pss.position_class = 'MID' AND pss.primary_position_class_v103 = 'FWD')
                  OR (pss.position_class = 'MID' AND pss.primary_position_class_v103 = 'DEF-MID')
                  OR (pss.position_class = 'MID' AND pss.primary_position_class_v103 = 'ATT-MID')
                  OR (pss.position_class = 'DEF' AND pss.primary_position_class_v103 = 'CENTRAL-MID')
              )
            ORDER BY pss.minutes DESC
            LIMIT 15
            """
        ).fetchall():
            print(f"  {r[0][:24]:<24} {r[1][:16]:<16} min={r[2]:>5} "
                  f"V1.02={r[3]:<4} V1.03={r[4]:<4} ({r[5]})")

        # Salah specifically — the canonical example.
        print("\n--- Salah's V1.03 positions (2025-2026) ---")
        for r in con.execute(
            """
            SELECT pp.priority, pp.position_code, pp.position_class,
                   pp.minutes_in_role, pp.n_matches, pp.position_source
            FROM player_positions_v103 pp
            JOIN players p USING (player_id)
            WHERE p.player_name = 'Mohamed Salah'
              AND pp.season = '2025-2026'
            ORDER BY pp.priority
            """
        ).fetchall():
            print(f"  priority={r[0]}  code={r[1]:<4}  class={r[2]:<12}  "
                  f"min={r[3]:>4}  n_matches={r[4]:>2}  src={r[5]}")

        # Fallback rows count.
        fallback_rows = con.execute(
            "SELECT COUNT(*) FROM player_positions_v103 "
            "WHERE position_source = 'fallback'"
        ).fetchone()[0]
        print(f"\nFallback rows in player_positions_v103: {fallback_rows}")
    finally:
        con.close()


if __name__ == "__main__":
    main()