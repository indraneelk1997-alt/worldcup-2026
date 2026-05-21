"""
V1.02 modeling — STEP 6c: MD38 prediction runner.

WHAT THIS DOES
    For each of the 10 MD38 fixtures:
      1. Looks up the home and away teams' rank-1 best XI from best_xi.
      2. Re-derives slot_no for each player by greedy-matching their
         position_class to the formation's formation_slots (so slot_no
         carries positional meaning in fixture_lineups).
      3. Creates ONE shared scenario per fixture:
            lineup_scenarios row (scenario_type='predicted')
            scenario_teams rows (home + away with their rank-1 formation)
            fixture_lineups rows (22, one per player, scenario-aware)
      4. Calls the V1.02 engine to run BOTH the unweighted and weighted
         variants against the shared scenario. Writes 2 predictions per
         fixture (20 total).
      5. Prints a side-by-side comparison of all 10 fixtures' two variants.

IDEMPOTENCY
    Wipes any existing 'predicted' scenarios for MD38 fixtures before
    writing. Re-running cleanly replaces the prediction set.
    NOTE: this only wipes scenario_type='predicted' rows tied to MD38
    fixtures. The legacy 'legacy_v1.01' scenario from S6 is untouched.

WHY ONE SCENARIO SHARED BETWEEN VARIANTS
    Both variants run against the same XIs. Differentiating predictions
    by `model_version` ('v1.02_unweighted' vs 'v1.02_weighted') is the
    natural separation — scenarios describe WHAT'S BEING PREDICTED, the
    model differentiates HOW.

HOW TO RUN
    From the repo root:
        uv run python src/simulate/run_md38_predictions.py
"""

import duckdb
from pathlib import Path
from datetime import datetime

# Import engine pieces.
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.simulate.poisson_sim_v102 import run_both_variants  # noqa: E402

DB_PATH = Path("data/processed/worldcup.duckdb")
TARGET_SEASON = "2025-2026"
SCENARIO_TYPE = "predicted"


# ---------------------------------------------------------------------------
# Slot assignment — match best_xi players to formation_slots positions
# ---------------------------------------------------------------------------
def assign_slots_by_class(formation_slot_rows, best_xi_players):
    """
    Greedy assignment: walk formation_slots in slot_no order; for each slot,
    pop the first best_xi player whose position_class matches that slot's
    class. Returns list of (slot_no, player_id) tuples (11 entries).

    formation_slot_rows: list of (slot_no, position_code, position_class),
        ordered by slot_no (1..11).
    best_xi_players: list of (slot_no_in_best_xi, player_id, position_class)
        — the slot_no_in_best_xi is ignored; we re-derive here.

    Raises if any slot can't be filled.
    """
    # Group best_xi players by class, preserve a stable order (by best_xi
    # slot_no, which was selection_score-ordered).
    by_class = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for _bxi_slot, pid, pc in sorted(best_xi_players, key=lambda r: r[0]):
        by_class[pc].append(pid)

    assignments = []  # list of (slot_no, player_id)
    for slot_no, _code, slot_class in formation_slot_rows:
        pool = by_class.get(slot_class, [])
        if not pool:
            raise SystemExit(
                f"Cannot fill slot {slot_no} ({slot_class}): no "
                f"{slot_class} player left in best XI. This shouldn't "
                f"happen if best_xi matches formation_slots — investigate."
            )
        player_id = pool.pop(0)
        assignments.append((slot_no, player_id))
    return assignments


# ---------------------------------------------------------------------------
# Per-fixture: build the scenario rows for one match
# ---------------------------------------------------------------------------
def build_scenario_rows(con, fixture_id, scenario_id, home_team,
                        away_team, season):
    """
    Look up rank-1 best XI for both teams and return the row tuples needed
    to insert lineup_scenarios + scenario_teams + fixture_lineups for one
    fixture. Does NOT write — pure computation.
    """
    side_data = {}
    for side, team in [("home", home_team), ("away", away_team)]:
        # 1. Fetch best XI for this team (rank=1).
        bxi_rows = con.execute("""
            SELECT slot_no, player_id, position_class
            FROM best_xi
            WHERE season = ? AND team = ? AND rank = 1
            ORDER BY slot_no
        """, [season, team]).fetchall()
        if len(bxi_rows) != 11:
            raise SystemExit(
                f"Expected 11 best_xi rows for {team} ({season}) rank=1, "
                f"got {len(bxi_rows)}."
            )

        # 2. Find the formation chosen for this team's rank-1 XI.
        formation = con.execute("""
            SELECT DISTINCT formation FROM best_xi
            WHERE season = ? AND team = ? AND rank = 1
        """, [season, team]).fetchone()[0]

        # 3. Fetch formation's slot definitions (1..11 with code + class).
        slot_rows = con.execute("""
            SELECT fs.slot_no, fs.position_code, p.position_class
            FROM formation_slots fs
            JOIN positions p ON p.position_code = fs.position_code
            WHERE fs.formation = ?
            ORDER BY fs.slot_no
        """, [formation]).fetchall()

        # 4. Re-derive slot_no by greedy class matching.
        assignments = assign_slots_by_class(slot_rows, bxi_rows)

        side_data[side] = {
            "team": team,
            "formation": formation,
            "assignments": assignments,
        }

    # 5. Build the row tuples.
    label = (
        f"MD38 {home_team} {side_data['home']['formation']} vs "
        f"{away_team} {side_data['away']['formation']}"
    )
    lineup_scenario_row = (
        scenario_id, fixture_id, SCENARIO_TYPE, label,
    )
    scenario_team_rows = [
        (scenario_id, "home", home_team, side_data["home"]["formation"]),
        (scenario_id, "away", away_team, side_data["away"]["formation"]),
    ]
    fixture_lineup_rows = []
    for side in ("home", "away"):
        for slot_no, player_id in side_data[side]["assignments"]:
            fixture_lineup_rows.append(
                (scenario_id, side, slot_no, player_id)
            )

    return lineup_scenario_row, scenario_team_rows, fixture_lineup_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    con = duckdb.connect(str(DB_PATH))
    try:
        # 1. Fetch MD38 fixtures.
        fixtures = con.execute("""
            SELECT fixture_id, home_team, away_team
            FROM fixtures
            WHERE matchday = 38 AND season = ?
            ORDER BY fixture_id
        """, [TARGET_SEASON]).fetchall()
        if not fixtures:
            raise SystemExit(
                f"No MD38 fixtures in DB for {TARGET_SEASON}. Run "
                f"src/load/load_md38_fixtures.py first."
            )
        print(f"Found {len(fixtures)} MD38 fixtures.\n")

        # 2. Wipe prior 'predicted' scenarios (and downstream) for these
        # fixtures. Idempotency: re-running the script replaces predictions.
        fixture_ids = [f[0] for f in fixtures]
        prior_scenarios = con.execute(
            f"""
            SELECT scenario_id FROM lineup_scenarios
            WHERE scenario_type = ?
              AND fixture_id IN ({','.join(['?'] * len(fixture_ids))})
            """,
            [SCENARIO_TYPE] + fixture_ids,
        ).fetchall()
        prior_ids = [r[0] for r in prior_scenarios]

        print("Beginning transaction...")
        con.execute("BEGIN TRANSACTION")
        try:
            if prior_ids:
                placeholders = ",".join(["?"] * len(prior_ids))
                print(f"  Wiping {len(prior_ids)} prior 'predicted' "
                      f"scenarios + downstream rows...")
                # Order: predictions -> fixture_lineups -> scenario_teams ->
                # lineup_scenarios (children before parents).
                con.execute(
                    f"DELETE FROM predictions WHERE scenario_id IN "
                    f"({placeholders})",
                    prior_ids,
                )
                con.execute(
                    f"DELETE FROM fixture_lineups WHERE scenario_id IN "
                    f"({placeholders})",
                    prior_ids,
                )
                con.execute(
                    f"DELETE FROM scenario_teams WHERE scenario_id IN "
                    f"({placeholders})",
                    prior_ids,
                )
                con.execute(
                    f"DELETE FROM lineup_scenarios WHERE scenario_id IN "
                    f"({placeholders})",
                    prior_ids,
                )

            # 3. Build all scenarios in memory before writing — fail-fast.
            # Get the next scenario_id (max existing + 1).
            max_sid = con.execute(
                "SELECT COALESCE(MAX(scenario_id), 0) FROM lineup_scenarios"
            ).fetchone()[0]
            next_sid = max_sid + 1

            all_scenario_rows = []  # list of dicts per fixture
            for fixture_id, home, away in fixtures:
                lsr, str_rows, fl_rows = build_scenario_rows(
                    con, fixture_id, next_sid, home, away, TARGET_SEASON,
                )
                all_scenario_rows.append({
                    "scenario_id": next_sid,
                    "fixture_id": fixture_id,
                    "home": home,
                    "away": away,
                    "lineup_scenario": lsr,
                    "scenario_teams": str_rows,
                    "fixture_lineups": fl_rows,
                })
                next_sid += 1

            # 4. Bulk inserts.
            print(f"  Inserting {len(all_scenario_rows)} scenarios + "
                  f"{2*len(all_scenario_rows)} scenario_teams + "
                  f"{22*len(all_scenario_rows)} fixture_lineups...")
            con.executemany(
                """
                INSERT INTO lineup_scenarios
                    (scenario_id, fixture_id, scenario_type, label)
                VALUES (?, ?, ?, ?)
                """,
                [s["lineup_scenario"] for s in all_scenario_rows],
            )
            con.executemany(
                """
                INSERT INTO scenario_teams
                    (scenario_id, side, team, formation)
                VALUES (?, ?, ?, ?)
                """,
                [r for s in all_scenario_rows for r in s["scenario_teams"]],
            )
            con.executemany(
                """
                INSERT INTO fixture_lineups
                    (scenario_id, side, slot_no, player_id)
                VALUES (?, ?, ?, ?)
                """,
                [r for s in all_scenario_rows for r in s["fixture_lineups"]],
            )

            # 5. Run both variants for each scenario. Each call writes
            # 2 predictions to the DB.
            print(f"\nRunning predictions (2 variants × "
                  f"{len(all_scenario_rows)} fixtures = "
                  f"{2 * len(all_scenario_rows)} predictions)...")
            results = []  # list of (fixture_id, home, away, both_variants_dict)
            for s in all_scenario_rows:
                both = run_both_variants(
                    con, s["scenario_id"], TARGET_SEASON,
                    label_for_log=f"{s['home']} vs {s['away']}",
                )
                results.append(
                    (s["fixture_id"], s["home"], s["away"], both)
                )

            con.execute("COMMIT")
            print("\nCOMMITTED.")
        except Exception:
            print("!!! Error during scenario/prediction writes, rolling back !!!")
            con.execute("ROLLBACK")
            raise

        # 6. Comparison table.
        print(f"\n{'='*100}")
        print(f"MD38 PREDICTIONS — V1.02 UNWEIGHTED vs WEIGHTED COMPARISON")
        print(f"{'='*100}")
        print(f"{'home':<18} {'away':<22} "
              f"{'variant':<12} {'xG home':>7} {'xG away':>7} "
              f"{'H%':>5} {'D%':>5} {'A%':>5} {'modal':>5}")
        print("-" * 100)
        for fixture_id, home, away, both in results:
            for variant in ("unweighted", "weighted"):
                d = both[variant]
                s = d["summary"]
                print(
                    f"{home[:18]:<18} {away[:22]:<22} "
                    f"{variant:<12} "
                    f"{d['xg_home']:>7.2f} {d['xg_away']:>7.2f} "
                    f"{s['p_home_win']*100:>4.1f}% "
                    f"{s['p_draw']*100:>4.1f}% "
                    f"{s['p_away_win']*100:>4.1f}% "
                    f"{s['modal_scoreline']:>5}"
                )
            print()  # blank line between fixtures

        # 7. Quick aggregate diff summary.
        print(f"{'='*100}")
        print("Aggregate variant divergence (|weighted - unweighted| > 5%)")
        print(f"{'='*100}")
        big_diffs = []
        for fixture_id, home, away, both in results:
            uw = both["unweighted"]["summary"]
            wt = both["weighted"]["summary"]
            for prob_key in ("p_home_win", "p_draw", "p_away_win"):
                diff_pct = (wt[prob_key] - uw[prob_key]) * 100
                if abs(diff_pct) > 5.0:
                    big_diffs.append(
                        (home, away, prob_key, uw[prob_key],
                         wt[prob_key], diff_pct)
                    )
        if not big_diffs:
            print("  None — variants agree within 5 percentage points "
                  "on all outcomes.")
        else:
            for home, away, key, uw_p, wt_p, diff in big_diffs:
                print(f"  {home[:15]:<15} vs {away[:18]:<18} {key:<11} "
                      f"{uw_p*100:>5.1f}% -> {wt_p*100:>5.1f}% "
                      f"({diff:+.1f} pts)")
    finally:
        con.close()


if __name__ == "__main__":
    main()