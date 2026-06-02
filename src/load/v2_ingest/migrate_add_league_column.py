"""
migrate_add_league_column.py  —  V1.04 schema migration (S16, build-seq step 1)

Adds a `league` discriminator column to the tables that become
multi-league under V1.04, backfills existing rows as Premier League,
then enforces NOT NULL so future inserts MUST name their league
explicitly (option B — no DEFAULT, no silent mislabeling of non-PL rows).

DuckDB rejects ADD COLUMN with an inline constraint, so the migration
runs as three supported steps per table:
  1. ADD COLUMN league VARCHAR          (plain; existing rows -> NULL)
  2. UPDATE ... SET league = PL          (explicit backfill of NULLs)
  3. ALTER COLUMN league SET NOT NULL    (guardrail; throws if any NULL)

Transaction semantics (S16 lesson, verified S17 via
src/load/v2_ingest/_verify_split_commit.py against DuckDB 1.5.2):
DuckDB raises "Cannot create index with outstanding updates" if
SET NOT NULL runs in the same transaction as the backfill UPDATE.
So this script uses split-commit: it does NOT wrap the migration in
an outer transaction. Each ALTER/UPDATE is autocommitted individually.

Trade-off: failure semantics are per-table rather than all-or-nothing
across tables. If table N fails, tables 1..N-1 are committed; tables
N+1..7 are not attempted. Re-run picks up at N via the idempotency
branch (column-present-but-still-nullable -> finish remaining work).
The migration is intentionally re-runnable.

FK-dependent tables (S17 lesson, verified live):
DuckDB refuses ALTER COLUMN SET NOT NULL on any table that other
tables hold a declared FK into ("Cannot alter entry 'X' because there
are entries that depend on it" — duckdb/duckdb#17348). There is no
DROP/ADD CONSTRAINT in DuckDB and no PRAGMA to disable FK tracking,
so the Postgres-style workarounds are closed (duckdb/duckdb#4204,
#4205). Mixed-enforcement policy:
  - Targets with NO declared FK dependents get the full
    ADD + UPDATE + SET NOT NULL (DB-level guard).
  - Targets WITH declared FK dependents get ADD + UPDATE only and
    stay nullable; V1.04 loaders enforce non-nullity in Python.
In this DB the FK-blocked targets are `games` and `fixtures`; the
other 5 targets get NOT NULL at the DB level. The script detects this
per table at runtime via duckdb_constraints(), so it adapts as the
FK graph changes (e.g. when a future table declares an FK into one
of the 5 currently-clean targets).

Idempotent: safe to run repeatedly. Per-table existence check before
ALTER, because DuckDB has no ADD COLUMN IF NOT EXISTS.

Observe-don't-infer (S14 lesson): the script PRINTS each table's
columns before and after acting, and reports exactly what it did.
You verify from its output; you don't trust it on faith.

Run (from repo root):
    uv run python src/load/v2_ingest/migrate_add_league_column.py
Dry-run (inspect only, no writes):
    uv run python src/load/v2_ingest/migrate_add_league_column.py --dry-run

Refs:
  DuckDB ALTER TABLE (ADD/DROP COLUMN, SET/DROP DEFAULT):
    https://duckdb.org/docs/sql/statements/alter_table
  DuckDB information_schema.columns:
    https://duckdb.org/docs/sql/information_schema
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

# --- config ----------------------------------------------------------------

DB_PATH = Path("data/processed/worldcup.duckdb")

PL_LEAGUE = "ENG-Premier League"

# Source of truth for which tables get the column. The pickup prose said
# "6 tables" but listed 7; the list wins until told otherwise.
TARGET_TABLES = [
    "games",
    "team_match_stats",
    "player_match_stats",
    "team_season_strength_v103",
    "league_averages_v103",
    "fixtures",
    "player_season_stats",
]

COL = "league"
COL_TYPE = "VARCHAR"


# --- helpers (all observe before acting) -----------------------------------

def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_name = ?",
        [table],
    ).fetchone()
    return bool(row and row[0])


def columns_of(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return [r[0] for r in rows]


def has_fk_dependents(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    """True if any other table holds a declared FK pointing to `table`.

    DuckDB blocks `ALTER COLUMN ... SET NOT NULL` on such tables
    ("Cannot alter entry 'X' because there are entries that depend on
    it" — duckdb/duckdb#17348). We work around by leaving those tables'
    `league` columns nullable and enforcing non-nullity in app code
    (V1.04 loaders). See module docstring.

    Note: `duckdb_constraints()` is known to miss some FKs
    (docs/db_schema.md "column-name graph" exists as a fallback), but
    misses err on the side of false negatives — i.e. we might attempt
    SET NOT NULL on a table that actually has an undeclared dependent,
    and DuckDB will raise. That failure is loud and the script's error
    handler names the offending table, so the operator can re-classify.
    """
    row = con.execute(
        "SELECT count(*) FROM duckdb_constraints() "
        "WHERE constraint_type = 'FOREIGN KEY' "
        "  AND referenced_table = ?",
        [table],
    ).fetchone()
    return bool(row and row[0])


# --- migration -------------------------------------------------------------

def migrate_table(
    con: duckdb.DuckDBPyConnection, table: str, dry_run: bool
) -> str:
    """Returns a one-line status string for the report.

    Branches on whether `table` has declared FK dependents:
      - No FK dependents → full ADD + UPDATE + SET NOT NULL.
      - Has FK dependents → ADD + UPDATE only; column stays nullable.
        V1.04 loaders enforce non-nullity in app code. See module docstring.
    """
    if not table_exists(con, table):
        return "SKIP (table absent)"

    cols_before = columns_of(con, table)
    has_col = COL in cols_before
    fk_blocked = has_fk_dependents(con, table)

    # DuckDB rejects ADD COLUMN with an inline constraint
    # ("Adding columns with constraints not yet supported"), so we
    # decompose into three supported steps:
    #   1. ADD COLUMN league VARCHAR           (plain; existing rows -> NULL)
    #   2. UPDATE ... SET league = PL WHERE league IS NULL   (explicit backfill)
    #   3. ALTER COLUMN league SET NOT NULL    (guardrail; fails if any NULL left)
    # Step 3 is SKIPPED for tables with FK dependents — DuckDB refuses
    # the alter ("Cannot alter entry 'X' because there are entries that
    # depend on it", S17, duckdb/duckdb#17348). See module docstring.
    #
    # No outer transaction wraps these steps — DuckDB cannot run step 3
    # in the same tx as step 2 ("Cannot create index with outstanding
    # updates", S16). Each statement autocommits.

    def nulls_remaining() -> int:
        row = con.execute(
            f"SELECT count(*) FROM {table} WHERE {COL} IS NULL"
        ).fetchone()
        return int(row[0]) if row else 0

    def is_not_null() -> bool:
        row = con.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            [table, COL],
        ).fetchone()
        return bool(row) and row[0] == "NO"

    fk_tag = " [FK-blocked: app-code enforces]" if fk_blocked else ""

    if has_col:
        # Column already present from a prior run. Finish idempotently.
        if fk_blocked:
            remaining = nulls_remaining()
            if remaining == 0:
                return (
                    f"already migrated (column present, fully backfilled){fk_tag}"
                )
            if dry_run:
                return (
                    f"column present; would backfill {remaining} NULL row(s) "
                    f"as PL{fk_tag}"
                )
            con.execute(
                f"UPDATE {table} SET {COL} = '{PL_LEAGUE}' WHERE {COL} IS NULL"
            )
            return f"completed partial backfill (backfilled {remaining}){fk_tag}"
        # Not FK-blocked: original 3-step idempotency path.
        if is_not_null():
            return "already migrated (column present, NOT NULL set)"
        remaining = nulls_remaining()
        if dry_run:
            return (
                f"column present but nullable; would backfill {remaining} "
                f"NULL row(s) as PL, then SET NOT NULL"
            )
        if remaining:
            con.execute(
                f"UPDATE {table} SET {COL} = '{PL_LEAGUE}' WHERE {COL} IS NULL"
            )
        con.execute(f"ALTER TABLE {table} ALTER COLUMN {COL} SET NOT NULL")
        return f"completed partial migration (backfilled {remaining}, SET NOT NULL)"

    # Column absent — fresh add.
    if dry_run:
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if fk_blocked:
            return (
                f"would ADD {COL} {COL_TYPE}, backfill {n} existing row(s) "
                f"as {PL_LEAGUE!r}{fk_tag}"
            )
        return (
            f"would ADD {COL} {COL_TYPE}, backfill {n} existing row(s) as "
            f"{PL_LEAGUE!r}, then SET NOT NULL (no DEFAULT)"
        )

    # 1. Plain add (no constraint) — existing rows get NULL.
    con.execute(f"ALTER TABLE {table} ADD COLUMN {COL} {COL_TYPE}")
    # 2. Explicit backfill of existing rows as PL.
    con.execute(
        f"UPDATE {table} SET {COL} = '{PL_LEAGUE}' WHERE {COL} IS NULL"
    )
    if fk_blocked:
        # Stop here for FK-dependent tables; app-code enforces non-nullity.
        return f"ADDED + backfilled PL{fk_tag}"
    # 3. Guardrail. Throws if any NULL slipped through (feature, not bug).
    con.execute(f"ALTER TABLE {table} ALTER COLUMN {COL} SET NOT NULL")
    return "ADDED + backfilled PL + SET NOT NULL"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change; make no writes.",
    )
    ap.add_argument(
        "--db", default=str(DB_PATH),
        help=f"Path to DuckDB file (default: {DB_PATH})",
    )
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 1

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE"
    print(f"=== migrate_add_league_column  [{mode}]  db={db} ===\n")

    # read_only mirrors dry-run intent; LIVE opens read-write.
    con = duckdb.connect(str(db), read_only=args.dry_run)
    try:
        # No outer transaction. Each table is its own unit of work; each
        # ALTER/UPDATE autocommits. See docstring "Transaction semantics".
        completed: list[str] = []
        try:
            for table in TARGET_TABLES:
                before = columns_of(con, table) if table_exists(con, table) else None
                status = migrate_table(con, table, args.dry_run)
                after = columns_of(con, table) if table_exists(con, table) else None
                print(f"[{table}]")
                print(f"   before: {before}")
                print(f"   action: {status}")
                print(f"   after : {after}\n")
                completed.append(table)
        except Exception:
            if not args.dry_run:
                idx = len(completed)
                remaining = TARGET_TABLES[idx + 1:] if idx < len(TARGET_TABLES) else []
                failed_on = (
                    TARGET_TABLES[idx] if idx < len(TARGET_TABLES) else "(unknown)"
                )
                print(
                    f"\n!! ERROR on table {failed_on!r}.\n"
                    f"   Committed (kept): {completed}\n"
                    f"   Not attempted  : {remaining}\n"
                    f"   Migration is idempotent — re-run after fixing the cause.",
                    file=sys.stderr,
                )
            raise
    finally:
        con.close()

    print("=== done ===")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())