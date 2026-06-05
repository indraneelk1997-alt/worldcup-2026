"""
ingest_understat.py  —  V1.04 Understat loader (S18, build-seq step 2).

INGEST ARCHITECTURE: v2 (append-only, source-centric)

Parametrized by `(league, season)`. Single Understat scraper instance,
shared cache across three reads, three table sections in this order:

  Section A — games               (read_schedule, one row per game)
  Section B — player_match_stats  (read_player_match_stats; needs
                                   compute_effective_position over the
                                   full season df before INSERT)
  Section C — team_match_stats    (read_team_match_stats; unpivot
                                   one Understat row -> two DB rows)

All design decisions banked in `docs/v104_ingest_understat.md`.
S17 mixed-enforcement: `games.league` is nullable at the DB level so
the loader asserts it explicitly per row (belt-and-suspenders on top
of the top-level league passthrough assertion).

Run from repo root:
    uv run python src/load/v2_ingest/ingest_understat.py \\
        --league "ESP-La Liga" --season "2024-2025"
Dry-run (no DB writes):
    uv run python src/load/v2_ingest/ingest_understat.py \\
        --league "ESP-La Liga" --season "2024-2025" --dry-run

Refs:
  soccerdata Understat: https://soccerdata.readthedocs.io/en/latest/datasources/Understat.html
  DuckDB INSERT OR IGNORE: https://duckdb.org/docs/sql/statements/insert
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd
import soccerdata as sd

# Allow `from _position_policy import ...` regardless of invocation style.
# Standard `python <script>` would do this anyway; being explicit is
# robust if someone later runs via `python -m` or imports as a module.
sys.path.insert(0, str(Path(__file__).parent))
from _position_policy import compute_effective_position  # noqa: E402


# --- config ---------------------------------------------------------------

DB_PATH = Path("data/processed/worldcup.duckdb")

# Understat MultiIndex `season` value <-> our DB `season` string.
# DB stores '2024-2025'; Understat returns '2425'. Same as V1.03's SEASON_MAP.
SEASON_DB_TO_SD = {
    "2024-2025": "2425",
    "2025-2026": "2526",
}
SEASON_SD_TO_DB = {v: k for k, v in SEASON_DB_TO_SD.items()}

# Currently supported leagues. Add to this set as we expand.
# All five top-tier European leagues are reachable via Understat per
# Claude.md "Understat / soccerdata notes".
SUPPORTED_LEAGUES = {
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
}


# --- assertions -----------------------------------------------------------

def assert_league_consistent(df, league_param: str, section_name: str) -> None:
    """Option C top-level assertion: every row's `league` value
    (whether in the MultiIndex or as a column) must equal --league.
    Mismatch -> hard fail, with both sides printed.
    """
    if df.index.names and "league" in df.index.names:
        seen = set(df.index.get_level_values("league").unique().tolist())
    elif "league" in df.columns:
        seen = set(df["league"].unique().tolist())
    else:
        raise AssertionError(
            f"{section_name}: no `league` in MultiIndex or columns. "
            f"soccerdata API shape may have changed."
        )
    if seen != {league_param}:
        raise AssertionError(
            f"{section_name}: league mismatch.\n"
            f"  --league param: {league_param!r}\n"
            f"  from Understat: {seen!r}\n"
            f"Refusing to load mixed-league data."
        )


def translate_season(df: pd.DataFrame, expected_db_season: str,
                     section_name: str) -> pd.DataFrame:
    """Add `season_db` column translated from Understat's `season`.
    Hard-fail if any row's season is unmappable or doesn't match
    --season."""
    df = df.copy()
    df["season_db"] = df["season"].astype(str).map(SEASON_SD_TO_DB)
    if df["season_db"].isna().any():
        bad = df.loc[df["season_db"].isna(), "season"].unique()
        raise SystemExit(
            f"{section_name}: unmapped seasons in Understat data: {bad}. "
            f"Add to SEASON_DB_TO_SD."
        )
    if not (df["season_db"] == expected_db_season).all():
        bad = df["season_db"].unique()
        raise SystemExit(
            f"{section_name}: --season {expected_db_season!r} does not "
            f"match data seasons {bad}."
        )
    return df


# --- section A: games -----------------------------------------------------

def ingest_games(con: duckdb.DuckDBPyConnection, df_sched: pd.DataFrame,
                 league: str, season_db: str, dry_run: bool) -> tuple[int, int]:
    """Returns (n_inserted, n_skipped_as_duplicate)."""
    df = df_sched.reset_index()
    df = translate_season(df, season_db, "games")

    # Build rows. league comes from the script param (already asserted
    # consistent with Understat at the top), but we ALSO assert per row
    # against the row's own league value as belt-and-suspenders for the
    # S17 obligation on `games` (nullable at DB level).
    rows = []
    for _, r in df.iterrows():
        row_league = r["league"] if "league" in df.columns else league
        assert row_league == league, (
            f"games: per-row league mismatch at game_id={r['game_id']}: "
            f"{row_league!r} vs {league!r}"
        )
        match_date = pd.to_datetime(r["date"]).date()
        rows.append((
            int(r["game_id"]),
            season_db,
            match_date,
            str(r["home_team"]),
            str(r["away_team"]),
            league,
        ))

    before = con.execute("SELECT count(*) FROM games").fetchone()[0]
    if dry_run:
        print(f"  rows constructed: {len(rows)}")
        print(f"  existing in DB:   {before}")
        if rows:
            print(f"  first row:        {rows[0]}")
        return (0, 0)

    con.executemany(
        "INSERT OR IGNORE INTO games "
        "(game_id, season, match_date, home_team, away_team, league) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    after = con.execute("SELECT count(*) FROM games").fetchone()[0]
    inserted = after - before
    return (inserted, len(rows) - inserted)


# --- section B: player_match_stats ----------------------------------------

def ingest_player_match(con: duckdb.DuckDBPyConnection, df_pms: pd.DataFrame,
                        league: str, season_db: str,
                        dry_run: bool) -> tuple[int, int]:
    df = df_pms.reset_index()
    df = translate_season(df, season_db, "player_match_stats")

    # --- precondition: maintain the `players` dimension table --------------
    # `player_match_stats.player_id` has a declared FK to `players.player_id`
    # (db_schema.md). New-league player_ids won't exist there yet, so we
    # INSERT OR IGNORE the (player_id, player_name) pairs first. Mirrors
    # V1.03's `backfill_player_match.py` step 10a. The `player` column
    # comes from the Understat MultiIndex level (player name string).
    player_pairs = (
        df[["player_id", "player"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    # Sanity: each player_id should map to exactly one player_name here.
    dup = player_pairs[player_pairs.duplicated("player_id", keep=False)]
    if len(dup):
        raise SystemExit(
            f"player_match: player_id maps to >1 player_name in this "
            f"dataset (data quality issue):\n{dup.to_string()}"
        )
    new_player_rows = [
        (int(r["player_id"]), str(r["player"]))
        for _, r in player_pairs.iterrows()
    ]

    existing_pids = {
        r[0] for r in con.execute("SELECT player_id FROM players").fetchall()
    }
    dataset_pids = {r[0] for r in new_player_rows}
    would_add = len(dataset_pids - existing_pids)
    print(f"  players: dataset has {len(dataset_pids)} distinct player_ids; "
          f"DB has {len(existing_pids)}; would add {would_add} new")
    if not dry_run:
        before_players = len(existing_pids)
        con.executemany(
            "INSERT OR IGNORE INTO players (player_id, player_name) "
            "VALUES (?, ?)",
            new_player_rows,
        )
        after_players = con.execute(
            "SELECT count(*) FROM players"
        ).fetchone()[0]
        print(f"  players inserted: {after_players - before_players}")

    # --- main player_match_stats path -------------------------------------
    # Step-3 fallback lookup. Empty for new-league loads per decision (a)
    # in docs/v104_ingest_understat.md. Still queried even in dry-run
    # (the connection is read-only then).
    season_class_lookup = {
        r[0]: r[1] for r in con.execute(
            "SELECT player_id, position_class FROM player_season_stats "
            "WHERE position_class IS NOT NULL"
        ).fetchall()
    }
    print(f"  loaded {len(season_class_lookup)} season-class lookups "
          f"for the policy-C step-2 fallback "
          f"({'expected non-empty for PL' if league == 'ENG-Premier League' else 'expected empty for fresh league'})")

    eff_lookup = compute_effective_position(df, season_class_lookup)

    # Build rows. The `team` column after reset_index comes from the
    # MultiIndex level (team name string), distinct from `team_id`.
    rows = []
    for _, r in df.iterrows():
        key = (int(r["game_id"]), int(r["player_id"]))
        rows.append((
            int(r["game_id"]),
            int(r["player_id"]),
            r["season_db"],
            str(r["team"]),
            str(r["position"]),
            eff_lookup[key],
            int(r["position_id"]),
            int(r["minutes"]),
            int(r["goals"]),
            int(r["own_goals"]),
            int(r["shots"]),
            float(r["xg"]),
            float(r["xg_chain"]),
            float(r["xg_buildup"]),
            int(r["assists"]),
            float(r["xa"]),
            int(r["key_passes"]),
            int(r["yellow_cards"]),
            int(r["red_cards"]),
            league,
        ))

    before = con.execute(
        "SELECT count(*) FROM player_match_stats"
    ).fetchone()[0]
    if dry_run:
        print(f"  rows constructed: {len(rows)}")
        print(f"  existing in DB:   {before}")
        if rows:
            print(f"  first row:        {rows[0]}")
        return (0, 0)

    con.executemany(
        """INSERT OR IGNORE INTO player_match_stats (
            game_id, player_id, season, team,
            position, effective_position, position_id,
            minutes, goals, own_goals, shots,
            xg, xg_chain, xg_buildup,
            assists, xa, key_passes,
            yellow_cards, red_cards,
            league
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    after = con.execute(
        "SELECT count(*) FROM player_match_stats"
    ).fetchone()[0]
    inserted = after - before
    return (inserted, len(rows) - inserted)


# --- section C: team_match_stats (unpivot) --------------------------------

def ingest_team_match(con: duckdb.DuckDBPyConnection, df_tms: pd.DataFrame,
                      league: str, season_db: str,
                      dry_run: bool) -> tuple[int, int]:
    """Understat returns one row per game with home_*/away_* paired
    columns. Our DB stores one row per (game, team). Unpivot:
    each Understat row -> two DB rows."""
    df = df_tms.reset_index()
    df = translate_season(df, season_db, "team_match_stats")

    rows = []
    for _, r in df.iterrows():
        gid = int(r["game_id"])
        # Home-side row: "this team" = home_team, opponent = away_team.
        rows.append((
            gid, str(r["home_team"]), "home", r["season_db"],
            str(r["away_team"]),
            int(r["home_points"]), float(r["home_expected_points"]),
            int(r["home_goals"]), int(r["away_goals"]),
            float(r["home_xg"]), float(r["away_xg"]),
            float(r["home_np_xg"]), float(r["away_np_xg"]),
            float(r["home_np_xg_difference"]),
            float(r["home_ppda"]), float(r["away_ppda"]),
            int(r["home_deep_completions"]),
            int(r["away_deep_completions"]),
            league,
        ))
        # Away-side row: "this team" = away_team, opponent = home_team.
        rows.append((
            gid, str(r["away_team"]), "away", r["season_db"],
            str(r["home_team"]),
            int(r["away_points"]), float(r["away_expected_points"]),
            int(r["away_goals"]), int(r["home_goals"]),
            float(r["away_xg"]), float(r["home_xg"]),
            float(r["away_np_xg"]), float(r["home_np_xg"]),
            float(r["away_np_xg_difference"]),
            float(r["away_ppda"]), float(r["home_ppda"]),
            int(r["away_deep_completions"]),
            int(r["home_deep_completions"]),
            league,
        ))

    before = con.execute(
        "SELECT count(*) FROM team_match_stats"
    ).fetchone()[0]
    if dry_run:
        print(f"  rows constructed: {len(rows)} (from {len(df)} games)")
        print(f"  existing in DB:   {before}")
        if rows:
            print(f"  first row:        {rows[0]}")
        return (0, 0)

    con.executemany(
        """INSERT OR IGNORE INTO team_match_stats (
            game_id, team, side, season, opponent,
            points, expected_points,
            goals, opponent_goals,
            xg, opponent_xg,
            np_xg, opponent_np_xg,
            np_xg_difference,
            ppda, opponent_ppda,
            deep_completions, opponent_deep_completions,
            league
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    after = con.execute(
        "SELECT count(*) FROM team_match_stats"
    ).fetchone()[0]
    inserted = after - before
    return (inserted, len(rows) - inserted)


# --- main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--league", required=True,
                    help=f"Understat league string. Supported: "
                         f"{sorted(SUPPORTED_LEAGUES)}")
    ap.add_argument("--season", required=True,
                    help=f"DB-format season string. Supported: "
                         f"{sorted(SEASON_DB_TO_SD)}")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + transform; print row counts; no DB writes.")
    args = ap.parse_args()

    if args.league not in SUPPORTED_LEAGUES:
        raise SystemExit(
            f"--league {args.league!r} not in SUPPORTED_LEAGUES "
            f"{sorted(SUPPORTED_LEAGUES)}"
        )
    if args.season not in SEASON_DB_TO_SD:
        raise SystemExit(
            f"--season {args.season!r} not in SEASON_DB_TO_SD "
            f"{sorted(SEASON_DB_TO_SD)}"
        )

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE"
    print(f"=== ingest_understat  [{mode}]  "
          f"league={args.league!r}  season={args.season!r} ===\n")

    season_sd = SEASON_DB_TO_SD[args.season]

    # One scraper, three reads. Each endpoint has its own cache file
    # so subsequent runs are cheap.
    print("Fetching from Understat (uses local cache)...")
    us = sd.Understat(leagues=[args.league], seasons=season_sd)
    df_sched = us.read_schedule()
    df_pms = us.read_player_match_stats()
    df_tms = us.read_team_match_stats()
    print(f"  schedule:     {len(df_sched):>6} rows")
    print(f"  player_match: {len(df_pms):>6} rows")
    print(f"  team_match:   {len(df_tms):>6} rows\n")

    # Option C: top-level league passthrough assertion on all three.
    for name, df in (("schedule", df_sched),
                     ("player_match", df_pms),
                     ("team_match", df_tms)):
        assert_league_consistent(df, args.league, name)
    print("Option C league assertion: OK across all three endpoints\n")

    if not DB_PATH.exists():
        raise SystemExit(f"ERROR: DB not found at {DB_PATH}")

    con = duckdb.connect(str(DB_PATH), read_only=args.dry_run)
    try:
        print("--- Section A: games ---")
        ins, skip = ingest_games(con, df_sched, args.league,
                                 args.season, args.dry_run)
        if not args.dry_run:
            print(f"  -> inserted={ins}, skipped_as_duplicate={skip}")
        print()

        print("--- Section B: player_match_stats ---")
        ins, skip = ingest_player_match(con, df_pms, args.league,
                                        args.season, args.dry_run)
        if not args.dry_run:
            print(f"  -> inserted={ins}, skipped_as_duplicate={skip}")
        print()

        print("--- Section C: team_match_stats ---")
        ins, skip = ingest_team_match(con, df_tms, args.league,
                                      args.season, args.dry_run)
        if not args.dry_run:
            print(f"  -> inserted={ins}, skipped_as_duplicate={skip}")
        print()
    finally:
        con.close()

    print("=== done ===")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
