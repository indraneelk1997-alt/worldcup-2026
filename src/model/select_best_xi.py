"""
V1.02 modeling — STEP 4 (b) — REVISED in S8 afternoon.

WHAT THIS DOES
    For each team in the target season, build candidate XIs for ALL 10
    formations in the library, rank them by total_xi_score, and store
    the top 3 in best_xi. The result: 33 rows per team (3 formations
    × 11 slots).

THE ALGORITHM
    For each team:
      1. Lock the GK by most minutes (deterministic across formations).
      2. For each of the 10 formations:
         a. Get the 10 outfielder slots (slot_no 2-11) with their
            position_code and position_class.
         b. Build a cost matrix where rows are eligible outfielders and
            columns are slots. cost[i, j] = -(blended_rating × class
            multiplier × slot bonus) if player i is eligible for slot j,
            else +infinity.
         c. Solve assignment with scipy.optimize.linear_sum_assignment.
            The Hungarian algorithm picks 10 distinct players, one per
            slot, maximizing total score.
         d. The XI's total_xi_score is the sum of all 10 outfielder
            selection_scores (GK contribution is 0; see S8 decision).
      3. Sort 10 candidate XIs by total_xi_score desc, keep top 3.
      4. Write 11 rows × 3 formations = 33 rows for this team.

MULTI-POSITION ELIGIBILITY (the heart of this rewrite)
    Each player has 1-4 eligible classes from player_positions. A player
    is eligible for slot j if their eligibility set contains the slot's
    position_class. So Szoboszlai ('DEF, FWD, MID') is eligible for any
    DEF, MID, or FWD slot. The Hungarian solver decides which role
    he fills, optimizing the WHOLE team's score.

POSITION MULTIPLIERS (S8 LOCKED VALUES, tuned mid-session)
    DEF: 2.0   MID: 1.25  FWD: 1.0   GK: not used (locked by minutes)
    Initial values (DEF=2, MID=1.5, FWD=1) produced a strong bias toward
    MID-heavy formations (14/20 teams picked 4-2-3-1 as their best fit).
    Dropped MID to 1.25 to reduce the bias while still acknowledging
    that defenders post lower rating_per_90 than forwards because
    rating_per_90 is npxG+xA (offensive). Formations do the heavy
    lifting of shape; multipliers only matter for intra-class ranking
    and inter-formation ranking.

HYBRID SLOT BONUS (S8 LOCKED RULE, tuned mid-session)
    Bonus dropped from 1.2 to 1.1 in the same tuning step as the MID
    multiplier above. Combined effect on hybrid MID slots: old was
    1.5 × 1.2 = 1.8x, new is 1.25 × 1.1 = 1.375x. ~24% less aggressive.

HYBRID SLOT BONUS DETAILED RULE (S8 LOCKED)
    If a slot's position_code is in {DM, CAM, LWB, RWB}:
        if player has BOTH "expected hybrid letters" in their Understat
        position string, multiply the score by HYBRID_SLOT_BONUS (1.1).
            DM, LWB, RWB     → expects DEF AND MID in player's classes
            CAM              → expects FWD AND MID in player's classes
        Otherwise no bonus.
    All other slots: no bonus.

GK CONTRIBUTION TO total_xi_score
    Zero. GK is locked-in deterministically (same player chosen
    regardless of formation), so including a GK contribution wouldn't
    affect formation ranking. Cleaner to set to 0.

HOW TO RUN
    From the repo root:
        uv run python src/model/select_best_xi.py
    Idempotent: wipes best_xi for the target season and re-inserts.
"""

import duckdb
import numpy as np
from scipy.optimize import linear_sum_assignment
from pathlib import Path

DB_PATH = Path("data/processed/worldcup.duckdb")

# --- locked decisions ------------------------------------------------------
TARGET_SEASON = "2025-2026"
FORM_WEIGHT = 0.75          # 0.75 form + 0.25 consistency, matches simulator
POSITION_MULTIPLIERS = {    # S8 tuned: 1/1.25/2, formation does heavy lifting
    "GK":  None,            # GK locked by minutes
    "DEF": 2.0,
    "MID": 1.25,
    "FWD": 1.0,
}
HYBRID_SLOT_BONUS = 1.1     # S8 tune: dropped from 1.2 after first run showed
                            # MID-heavy formations dominating. 1.1 is gentler.
HYBRID_SLOT_RULES = {
    # slot_code -> (set of classes that must ALL be in player's eligibility)
    "DM":  {"DEF", "MID"},
    "CAM": {"FWD", "MID"},
    "LWB": {"DEF", "MID"},
    "RWB": {"DEF", "MID"},
}
NUM_TOP_FORMATIONS_TO_STORE = 3
INELIGIBLE_COST = 1e9       # "infinity" for the cost matrix; very large but finite


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def compute_pair_score(blended_rating, player_classes, slot_code, slot_class):
    """
    Return the selection_score for assigning this player to this slot,
    or None if ineligible.

    Score = blended_rating × class_multiplier × hybrid_bonus
    """
    if slot_class not in player_classes:
        return None  # ineligible: player can't play this class
    multiplier = POSITION_MULTIPLIERS[slot_class]
    if multiplier is None:
        # Shouldn't happen — GK isn't in the cost matrix.
        return None
    bonus = 1.0
    rule = HYBRID_SLOT_RULES.get(slot_code)
    if rule is not None and rule.issubset(player_classes):
        bonus = HYBRID_SLOT_BONUS
    return blended_rating * multiplier * bonus


# ---------------------------------------------------------------------------
# Per-team selection
# ---------------------------------------------------------------------------
def select_for_team(con, team, season, formations_slot_data, blended_lookup,
                    positions_lookup):
    """
    Return a list of dicts, one per stored XI:
      [
        {'formation': '4-3-3', 'rank': 1, 'total': 5.2, 'rows': [11 row tuples]},
        ...
      ]

    Builds 10 candidate XIs (one per formation), keeps top 3.
    """
    # 1. Lock GK.
    gk_row = con.execute(
        """
        SELECT pss.player_id, pss.minutes
        FROM player_season_stats pss
        WHERE pss.team = ? AND pss.season = ?
          AND pss.position_class = 'GK'
        ORDER BY pss.minutes DESC, pss.player_id ASC
        LIMIT 1
        """,
        [team, season],
    ).fetchone()
    if gk_row is None:
        raise SystemExit(
            f"FAIL: no GK found for {team} in {season}. "
            f"Cannot assemble best XI."
        )
    gk_player_id, gk_minutes = gk_row

    # 2. Eligible outfielders: every non-GK player on this team-season
    # with at least one non-GK class in player_positions and non-null
    # shrunk values. (Shrunk values were guaranteed by S7's compute step.)
    outfielders = con.execute(
        """
        SELECT pss.player_id, pss.minutes, pss.position_class
        FROM player_season_stats pss
        WHERE pss.team = ? AND pss.season = ?
          AND pss.position_class != 'GK'
          AND pss.shrunk_form IS NOT NULL
          AND pss.shrunk_consistency IS NOT NULL
        """,
        [team, season],
    ).fetchall()

    if len(outfielders) < 10:
        raise SystemExit(
            f"FAIL: {team} in {season} has only {len(outfielders)} eligible "
            f"outfielders (need ≥10). Cannot assemble best XI."
        )

    outfielder_ids = [r[0] for r in outfielders]
    minutes_lookup = {r[0]: r[1] for r in outfielders}
    primary_class_lookup = {r[0]: r[2] for r in outfielders}

    # 3. For each formation, build cost matrix + solve assignment.
    candidate_xis = []  # list of (formation, total_score, list of (slot_no, pid, class, score))

    for formation, slot_records in formations_slot_data.items():
        # slot_records: list of 10 (slot_no, position_code, position_class)
        # for the OUTFIELDER slots (slot_no 2..11)
        n_players = len(outfielder_ids)
        n_slots = len(slot_records)  # should always be 10
        assert n_slots == 10, f"{formation} has {n_slots} outfielder slots"

        # Build cost matrix. rows=players, cols=slots.
        # cost[i,j] = -(score) for eligible pairs, INELIGIBLE_COST otherwise.
        cost = np.full((n_players, n_slots), INELIGIBLE_COST, dtype=np.float64)
        score_matrix = np.zeros((n_players, n_slots), dtype=np.float64)

        for i, pid in enumerate(outfielder_ids):
            blended = blended_lookup[(pid, season, team)]
            classes = positions_lookup[(pid, season, team)]
            for j, (slot_no, slot_code, slot_class) in enumerate(slot_records):
                score = compute_pair_score(blended, classes, slot_code, slot_class)
                if score is not None:
                    cost[i, j] = -score
                    score_matrix[i, j] = score

        # 4. Solve. scipy returns row_ind[j] for each col j: the row chosen
        # for column j. With more rows than columns, it picks the best n_slots
        # rows out of n_players.
        try:
            row_ind, col_ind = linear_sum_assignment(cost)
        except ValueError as e:
            raise SystemExit(
                f"FAIL: assignment problem unsolvable for {team} / {formation}: {e}"
            )

        # 5. Compute total score and extract assignment.
        assigned_rows = []  # list of (slot_no, pid, slot_class, score)
        total_score = 0.0
        infeasible = False
        for r, c in zip(row_ind, col_ind):
            slot_no, slot_code, slot_class = slot_records[c]
            pid = outfielder_ids[r]
            score = score_matrix[r, c]
            # If the assigned cost was INELIGIBLE_COST, we have an infeasible
            # solve (not enough eligible players for some class). Catch.
            if cost[r, c] >= INELIGIBLE_COST:
                infeasible = True
                break
            assigned_rows.append((slot_no, pid, slot_class, score))
            total_score += score

        if infeasible:
            # Skip this formation for this team. Not fatal — other formations
            # may still be feasible. Print so we know it happened.
            print(f"    [SKIP] {team} cannot fill {formation} (insufficient "
                  f"eligible players for some position class).")
            continue

        candidate_xis.append((formation, total_score, assigned_rows))

    if not candidate_xis:
        raise SystemExit(
            f"FAIL: {team} could not fill ANY of the 10 formations. "
            f"Investigate squad eligibility."
        )

    # 6. Sort by total_score DESC, keep top 3.
    candidate_xis.sort(key=lambda x: -x[1])
    top_candidates = candidate_xis[:NUM_TOP_FORMATIONS_TO_STORE]

    # 7. Build the output rows: GK at slot 1, outfielders at their assigned
    # slot_nos (which are 2-11). selection_score NULL for GK.
    result = []
    for rank, (formation, total, assigned) in enumerate(top_candidates, start=1):
        rows = [
            # GK row: slot 1
            (season, team, formation, rank, 1, gk_player_id, "GK",
             gk_minutes, None, total)
        ]
        for slot_no, pid, slot_class, score in assigned:
            rows.append(
                (season, team, formation, rank, slot_no, pid, slot_class,
                 minutes_lookup[pid], score, total)
            )
        # Sort by slot_no so DB insert ordering is predictable
        rows.sort(key=lambda r: r[4])
        result.append({"formation": formation, "rank": rank,
                       "total": total, "rows": rows})
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"DB not found at {DB_PATH} — run this from the repo root."
        )

    con = duckdb.connect(str(DB_PATH))
    try:
        # Sanity: required tables.
        existing = {
            r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        for required in ("best_xi", "player_positions", "formation_slots",
                         "formations"):
            if required not in existing:
                raise SystemExit(
                    f"Required table '{required}' missing. Run prerequisite "
                    f"schema scripts first."
                )

        # 1. Pre-load reference data into memory for fast inner-loop access.

        # 1a. Outfielder slots per formation: (slot_no, code, class).
        slot_rows = con.execute(
            """
            SELECT fs.formation, fs.slot_no, fs.position_code, p.position_class
            FROM formation_slots fs
            JOIN positions p ON p.position_code = fs.position_code
            WHERE fs.slot_no >= 2   -- outfielders only; slot 1 is the GK
            ORDER BY fs.formation, fs.slot_no
            """
        ).fetchall()
        formations_slot_data = {}
        for formation, slot_no, code, cls in slot_rows:
            formations_slot_data.setdefault(formation, []).append(
                (slot_no, code, cls)
            )
        print(f"Loaded {len(formations_slot_data)} formations × "
              f"{len(formations_slot_data[next(iter(formations_slot_data))])}"
              f" outfielder slots.")

        # 1b. Blended rating per (player_id, season, team).
        blended_rows = con.execute(
            """
            SELECT player_id, season, team,
                   ? * shrunk_form + ? * shrunk_consistency AS blended
            FROM player_season_stats
            WHERE season = ?
              AND shrunk_form IS NOT NULL
              AND shrunk_consistency IS NOT NULL
            """,
            [FORM_WEIGHT, 1 - FORM_WEIGHT, TARGET_SEASON],
        ).fetchall()
        blended_lookup = {(pid, s, t): b for pid, s, t, b in blended_rows}
        print(f"Loaded {len(blended_lookup)} blended ratings for "
              f"{TARGET_SEASON}.")

        # 1c. Eligible classes per (player_id, season, team).
        pp_rows = con.execute(
            """
            SELECT player_id, season, team, position_class
            FROM player_positions
            WHERE season = ?
            """,
            [TARGET_SEASON],
        ).fetchall()
        positions_lookup = {}
        for pid, s, t, cls in pp_rows:
            positions_lookup.setdefault((pid, s, t), set()).add(cls)
        print(f"Loaded positions for {len(positions_lookup)} player-team rows.")

        # 2. Distinct teams.
        teams = [
            r[0] for r in con.execute(
                "SELECT DISTINCT team FROM player_season_stats "
                "WHERE season = ? ORDER BY team",
                [TARGET_SEASON],
            ).fetchall()
        ]
        print(f"Building best XIs for {len(teams)} teams.\n")

        # 3. Run selection per team. Accumulate rows; commit at the end.
        all_rows = []
        per_team_summary = []   # (team, [(formation, rank, total)] for top 3)
        for team in teams:
            print(f"  {team}...")
            team_xis = select_for_team(
                con, team, TARGET_SEASON, formations_slot_data,
                blended_lookup, positions_lookup,
            )
            summary = []
            for xi in team_xis:
                summary.append((xi["formation"], xi["rank"], xi["total"]))
                all_rows.extend(xi["rows"])
            per_team_summary.append((team, summary))

        print(f"\nAssembled {len(all_rows)} rows across all teams "
              f"(expected: {len(teams) * 3 * 11} = {len(teams)}*3*11).")

        # 4. Write in a transaction. Wipe season first.
        print(f"\nClearing best_xi for {TARGET_SEASON}...")
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                "DELETE FROM best_xi WHERE season = ?", [TARGET_SEASON],
            )
            con.executemany(
                """
                INSERT INTO best_xi
                    (season, team, formation, rank, slot_no, player_id,
                     position_class, minutes, selection_score, total_xi_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                all_rows,
            )
            inserted = con.execute(
                "SELECT COUNT(*) FROM best_xi WHERE season = ?",
                [TARGET_SEASON],
            ).fetchone()[0]
            if inserted != len(all_rows):
                raise SystemExit(
                    f"Insert mismatch: tried {len(all_rows)}, see {inserted}. "
                    f"Rolling back."
                )
            con.execute("COMMIT")
            print(f"COMMITTED. {inserted} rows written.")
        except Exception:
            print("!!! Error during insert, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 5. SANITY OUTPUT — per-team top-3 formation summary.
        print(f"\n--- Top 3 formations per team ({TARGET_SEASON}) ---")
        print(f"{'team':<18} {'#1':<28} {'#2':<28} {'#3':<28}")
        for team, summary in per_team_summary:
            cells = []
            for f, r, t in summary:
                cells.append(f"{f} ({t:.2f})")
            while len(cells) < 3:
                cells.append("--")
            print(f"{team[:18]:<18} {cells[0]:<28} {cells[1]:<28} {cells[2]:<28}")

        # 6. Distribution of #1 formations across teams.
        print(f"\n--- Which formation 'wins' for each team ---")
        winning = con.execute(
            """
            SELECT formation, COUNT(DISTINCT team) AS n_teams
            FROM best_xi
            WHERE season = ? AND rank = 1
            GROUP BY formation
            ORDER BY n_teams DESC, formation
            """,
            [TARGET_SEASON],
        ).fetchall()
        for formation, n_teams in winning:
            print(f"  {formation:<10} {n_teams:>2} teams")

        # 7. The big one — Liverpool's three best XIs in detail.
        print(f"\n--- Liverpool: top 3 XIs in detail ---")
        for rank in (1, 2, 3):
            rows = con.execute(
                """
                SELECT bxi.formation, bxi.slot_no, p.player_name,
                       bxi.position_class, bxi.minutes,
                       bxi.selection_score, bxi.total_xi_score
                FROM best_xi bxi
                JOIN players p USING (player_id)
                WHERE bxi.team = 'Liverpool' AND bxi.season = ? AND bxi.rank = ?
                ORDER BY bxi.slot_no
                """,
                [TARGET_SEASON, rank],
            ).fetchall()
            if not rows:
                continue
            formation = rows[0][0]
            total = rows[0][6]
            print(f"\n  Rank {rank}: {formation}  (total = {total:.3f})")
            print(f"  {'slot':>4} {'player':<26} {'cls':<5} {'min':>5} "
                  f"{'score':>7}")
            for _, slot_no, name, pc, mins, score, _ in rows:
                score_str = f"{score:.3f}" if score is not None else "  (GK)"
                print(f"  {slot_no:>4} {name[:26]:<26} {pc:<5} {mins:>5} "
                      f"{score_str:>7}")

        # 8. Class distribution across all rank=1 XIs.
        print(f"\n--- Class distribution across all rank=1 XIs ---")
        rows = con.execute(
            """
            SELECT position_class, COUNT(*) AS n
            FROM best_xi
            WHERE season = ? AND rank = 1
            GROUP BY position_class
            ORDER BY position_class
            """,
            [TARGET_SEASON],
        ).fetchall()
        for pc, n in rows:
            print(f"  {pc:<5} {n:>4}")
    finally:
        con.close()


if __name__ == "__main__":
    main()