"""
S22 observe gate — dump the real shapes we need BEFORE writing migration
+ loader code. Honors the S14 lesson (observe, don't infer): we read the
actual columns off disk instead of guessing them from the design docs.

What it checks (maps to the 4 pre-flight gates in
docs/v104_schema_migration.md):

  A. DB (read-only): FK graph into `games`, current columns on the three
     shared dimensions (games/players/positions), and the live
     position_class vocabulary. -> gate 2, + idempotency baselines.
  B. read_schedule (cache): columns, game_id dtype, the real `score`
     strings incl. any shootout/aet, round labels, venue. -> gate 4 (c),
     and the authoritative game_id set for the decision-(g) filter.
  C. read_team_match_stats (cache): MultiIndex columns + whether
     `game_id` is exposed as a column/index level or must be parsed from
     match_report. -> gate 3.
  D. read_player_match_stats summary (cache): exact MultiIndex leaf
     names (to freeze FBREF_COL_MAP), plus real `pos` and `age` values.
     -> gate 4 (d, e, f).

SAFETY:
  * DB opened read_only=True — zero writes.
  * FBref reads should be pure CACHE HITS from the S21 run (instant /
    seconds of re-parsing, no HTTP). If you see soccerdata start logging
    "[i/189] Retrieving game with id=..." with ~7s pauses, that's a
    CACHE MISS hitting the network — Ctrl-C and tell me, don't sit
    through the 70-min sweep.

Does NOT touch the schema. Deletable once migration + loader land.

Run:
    uv run python src/load/v2_ingest/_probe_s22_schema_shapes.py
"""

from __future__ import annotations

import sys
import traceback

import duckdb
import pandas as pd

DB_PATH = "data/processed/worldcup.duckdb"
UCL_LEAGUE_KEY = "UEFA-Champions League"
UCL_SEASON = "2024-2025"

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 60)


def section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def dump_columns(df, name: str, max_rows: int = 5) -> None:
    print(f"\n  {name}: {len(df)} rows")
    print(f"  index names: {df.index.names}")
    print(f"  columns ({len(df.columns)}):")
    for c in df.columns:
        print(f"    - {c!r}")
    print(f"\n  head({max_rows}):")
    print(df.head(max_rows).to_string())


# ---------------------------------------------------------------- A. DB
def probe_db() -> None:
    section("A) DB (read-only): FK graph + shared-dimension columns")
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        fks = con.execute(
            "SELECT * FROM duckdb_constraints() "
            "WHERE constraint_type = 'FOREIGN KEY'"
        ).fetchdf()
        print("\n  -- all FOREIGN KEY constraints (duckdb_constraints) --")
        # show the columns that exist in this duckdb version
        keep = [c for c in
                ("table_name", "constraint_column_names",
                 "referenced_table", "referenced_column_names",
                 "constraint_text")
                if c in fks.columns]
        print(fks[keep].to_string() if keep else fks.to_string())
        print("\n  (caveat: duckdb_constraints() under-reports — cross-check")
        print("   against the column-name graph in docs/db_schema.md.)")

        for t in ("games", "players", "positions"):
            cols = con.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                f"WHERE table_name = '{t}' ORDER BY ordinal_position"
            ).fetchdf()
            print(f"\n  -- {t} columns --")
            print(cols.to_string())

        print("\n  -- positions.position_class distinct vocabulary --")
        print(con.execute(
            "SELECT DISTINCT position_class FROM positions ORDER BY 1"
        ).fetchdf().to_string())
        print("\n  -- positions sample (flank is NOT NULL — note values) --")
        print(con.execute(
            "SELECT position_code, position_class, flank FROM positions "
            "ORDER BY position_code LIMIT 25"
        ).fetchdf().to_string())
    finally:
        con.close()


# --------------------------------------------------------- FBref reads
def probe_fbref() -> None:
    from soccerdata import FBref

    if UCL_LEAGUE_KEY not in FBref.available_leagues():
        print(f"\nFAIL — '{UCL_LEAGUE_KEY}' not in FBref.available_leagues().")
        print("  Run: uv run python src/tools/setup_soccerdata_overlay.py")
        return

    scraper = FBref(leagues=[UCL_LEAGUE_KEY], seasons=UCL_SEASON)

    # ---- B. read_schedule ----
    section("B) read_schedule (cache): score / round / venue / game_id")
    try:
        sched = scraper.read_schedule()
        dump_columns(sched, "read_schedule")

        # game_id: column or index level? what dtype?
        in_cols = "game_id" in [str(c) for c in sched.columns]
        in_idx = "game_id" in [str(n) for n in (sched.index.names or [])]
        print(f"\n  game_id in columns? {in_cols}   in index? {in_idx}")
        if in_cols:
            print(f"  game_id dtype: {sched['game_id'].dtype}")
            print(f"  game_id samples: "
                  f"{sched['game_id'].dropna().head(5).tolist()}")

        if "score" in sched.columns:
            sc = sched["score"].astype(str)
            print("\n  -- score values containing '(' (shootout/aet) --")
            hit = sched.loc[sc.str.contains(r"\(", na=False)]
            cols = [c for c in ("round", "score") if c in sched.columns]
            print(hit[cols].to_string() if len(hit) else "    (none found)")
            print("\n  -- 8 sample score strings (note the dash character) --")
            for v in sched["score"].dropna().head(8).tolist():
                print(f"    {v!r}")

        if "round" in sched.columns:
            print("\n  -- distinct round labels --")
            print("   ", sorted(sched["round"].dropna().astype(str).unique()))
        if "venue" in sched.columns:
            print("\n  -- venue samples --")
            print("   ", sched["venue"].dropna().head(5).tolist())
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ---- C. read_team_match_stats ----
    section("C) read_team_match_stats(stat_type='schedule') (cache)")
    print("  (all-comps contaminated by design — we want game_id exposure)")
    try:
        tm = scraper.read_team_match_stats(stat_type="schedule")
        dump_columns(tm, "team_match(schedule)", max_rows=3)
        flat = [str(c) for c in tm.columns]
        idxn = [str(n) for n in (tm.index.names or [])]
        print(f"\n  game_id in columns? {'game_id' in flat}")
        print(f"  game_id in index?   {'game_id' in idxn}")
        mr = [c for c in tm.columns if "match" in str(c).lower()
              and "report" in str(c).lower()]
        print(f"  match_report-like columns: {mr}")
        if mr:
            print(f"  match_report sample: {tm[mr[0]].dropna().head(2).tolist()}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ---- D. read_player_match_stats ----
    section("D) read_player_match_stats(stat_type='summary') (cache)")
    print("  EXPECT INSTANT (cache). If it logs '[i/189] Retrieving...'")
    print("  with 7s pauses -> cache miss, Ctrl-C and tell me.")
    try:
        pm = scraper.read_player_match_stats(stat_type="summary")
        print(f"\n  shape: {pm.shape}")
        print(f"  index names: {pm.index.names}")
        print("\n  columns (raw MultiIndex tuples — this freezes FBREF_COL_MAP):")
        for c in pm.columns:
            print(f"    {c!r}")
        # find pos / age columns by leaf name
        def leaf(c):
            return str(c[-1] if isinstance(c, tuple) else c).lower()
        pos_cols = [c for c in pm.columns if leaf(c) in ("pos", "position")]
        age_cols = [c for c in pm.columns if leaf(c) == "age"]
        if pos_cols:
            print(f"\n  -- distinct pos values ({pos_cols[0]!r}) --")
            print("   ", sorted(pm[pos_cols[0]].dropna().astype(str).unique())[:40])
        if age_cols:
            print(f"\n  -- sample age values ({age_cols[0]!r}) --")
            print("   ", pm[age_cols[0]].dropna().astype(str).head(8).tolist())
        print("\n  head(3):")
        print(pm.head(3).to_string())
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()


def main() -> int:
    section("S22 observe gate — schema-relevant shapes (read-only)")
    print(f"  DB:     {DB_PATH}  (read_only)")
    print(f"  league: {UCL_LEAGUE_KEY}")
    print(f"  season: {UCL_SEASON}")
    try:
        probe_db()
    except Exception as e:
        print(f"\n  DB probe FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
    try:
        probe_fbref()
    except Exception as e:
        print(f"\n  FBref probe FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
    section("done — paste the full output back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
