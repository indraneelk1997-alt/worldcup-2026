"""
V1.03 modeling — S15 tooling: schema reference doc generator.

WHAT THIS DOES
    Queries the DuckDB at data/processed/worldcup.duckdb and writes a
    markdown reference doc to docs/db_schema.md describing the full
    schema, including:
      - per-table column listings (name, type, nullability, PK flag)
      - declared foreign key constraints (per duckdb_constraints())
      - row counts
      - one sample row per table
      - the COLUMN-NAME GRAPH: every column name appearing in 2+ tables

WHY THE COLUMN-NAME GRAPH MATTERS
    DuckDB's information_schema / duckdb_constraints() does not reliably
    surface all FK constraints (S14 discovered this — we had at least 3
    real FKs to games(game_id) but only 2 showed in catalog queries).

    The column-name graph is a defensive layer: any column appearing
    in 2+ tables is flagged so the reader can manually identify FK
    relationships the catalog missed. Yes, this is noisy (`season`
    appears in ~15 tables and is dimensional, not relational), but
    noise is preferable to silent FK-graph gaps.

WHAT IT INTENTIONALLY DOESN'T DO
    - No "smart" filtering of dimensional vs relational columns. The
      human reader judges; the script just surfaces.
    - No JSON output. Markdown only.
    - No automatic regeneration. Manual run; convention is to
      regenerate after any commit that modifies a CREATE TABLE.

HOW TO RUN
    From the repo root:
        uv run python src/tools/dump_db_schema.py
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb

DB_PATH = Path("data/processed/worldcup.duckdb")
OUT_PATH = Path("docs/db_schema.md")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def list_tables(con):
    """All user-defined tables (excludes views and system tables)."""
    return [
        r[0] for r in con.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """).fetchall()
    ]


def describe_table(con, table_name):
    """List of (col_name, col_type, nullable, is_pk)."""
    rows = con.execute(f"DESCRIBE {table_name}").fetchall()
    out = []
    for r in rows:
        col_name = r[0]
        col_type = r[1]
        nullable = r[2] == "YES"
        is_pk = r[3] == "PRI"
        out.append((col_name, col_type, nullable, is_pk))
    return out


def fetch_declared_fks(con):
    """
    Returns dict {table_name -> list of (cols, ref_table, ref_cols)}.
    Uses duckdb_constraints(); known to be incomplete in some DBs
    (S14 lesson), so this is a 'best effort' view.
    """
    rows = con.execute("""
        SELECT table_name, constraint_column_names,
               referenced_table, referenced_column_names
        FROM duckdb_constraints()
        WHERE constraint_type = 'FOREIGN KEY'
        ORDER BY table_name, constraint_column_names
    """).fetchall()
    by_table = defaultdict(list)
    for table, cols, ref_table, ref_cols in rows:
        by_table[table].append((cols, ref_table, ref_cols))
    return dict(by_table)


def row_count(con, table_name):
    return con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


def sample_row(con, table_name):
    """Returns one row as dict, or None if empty."""
    n = row_count(con, table_name)
    if n == 0:
        return None
    cols = [c[0] for c in describe_table(con, table_name)]
    row = con.execute(f"SELECT * FROM {table_name} LIMIT 1").fetchone()
    return dict(zip(cols, row))


def build_column_name_graph(con, tables):
    """
    Returns dict {column_name -> list of (table, is_pk_in_table)}.
    Only includes column names appearing in 2+ tables.
    """
    appearances = defaultdict(list)  # col_name -> [(table, is_pk), ...]
    for table in tables:
        for col_name, _type, _null, is_pk in describe_table(con, table):
            appearances[col_name].append((table, is_pk))
    # Filter to columns appearing in 2+ tables.
    return {k: v for k, v in appearances.items() if len(v) >= 2}


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def render_table_section(con, table_name, declared_fks):
    """Markdown chunk for one table."""
    lines = [f"### `{table_name}`", ""]
    n = row_count(con, table_name)
    lines.append(f"**Rows**: {n:,}")
    lines.append("")

    # Columns table.
    lines.append("| Column | Type | Nullable | PK |")
    lines.append("|---|---|---|---|")
    for col_name, col_type, nullable, is_pk in describe_table(con, table_name):
        null_str = "YES" if nullable else "NO"
        pk_str = "✓" if is_pk else ""
        lines.append(f"| `{col_name}` | `{col_type}` | {null_str} | {pk_str} |")
    lines.append("")

    # FKs (declared).
    fks = declared_fks.get(table_name, [])
    if fks:
        lines.append("**Declared foreign keys** (per `duckdb_constraints()`):")
        lines.append("")
        for cols, ref_table, ref_cols in fks:
            cols_str = ", ".join(f"`{c}`" for c in cols)
            ref_cols_str = ", ".join(f"`{c}`" for c in ref_cols)
            lines.append(f"- ({cols_str}) → `{ref_table}` ({ref_cols_str})")
        lines.append("")
    else:
        lines.append("**Declared foreign keys**: none")
        lines.append("")

    # Sample row.
    sample = sample_row(con, table_name)
    if sample is None:
        lines.append("**Sample row**: (empty table)")
    else:
        lines.append("**Sample row**:")
        lines.append("")
        lines.append("```")
        for k, v in sample.items():
            v_str = repr(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + "..."
            lines.append(f"  {k} = {v_str}")
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_column_name_graph(graph):
    """
    Markdown chunk for the column-name graph.

    Sorted by (num_tables descending, column_name ascending) so the most
    widely-shared columns appear first.
    """
    lines = [
        "## Column-name graph",
        "",
        ("> These column names appear in 2+ tables. Some are real "
         "FK relationships (declared or NOT — `duckdb_constraints()` "
         "is known to miss some, see S14 carry-forward). Some are "
         "dimensional values that happen to share names (e.g. `season`, "
         "`model_version`). Inspect manually."),
        "",
    ]
    sorted_items = sorted(
        graph.items(),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
    for col_name, appearances in sorted_items:
        n_tables = len(appearances)
        lines.append(f"### `{col_name}` ({n_tables} tables)")
        lines.append("")
        for table, is_pk in sorted(appearances):
            pk_str = " *(PK)*" if is_pk else ""
            lines.append(f"- `{table}`{pk_str}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        tables = list_tables(con)
        declared_fks = fetch_declared_fks(con)
        graph = build_column_name_graph(con, tables)

        # Build the markdown document.
        chunks = []
        chunks.append("# DuckDB schema reference\n")
        chunks.append(
            f"_Generated: {datetime.now().isoformat(timespec='seconds')}_  \n"
            f"_DB: `{DB_PATH}`_  \n"
            f"_Tables: {len(tables)}_  \n"
        )
        chunks.append("")
        chunks.append(
            "This file is auto-generated. Do not edit by hand. "
            "Regenerate with:\n"
            "```\n"
            "uv run python src/tools/dump_db_schema.py\n"
            "```\n"
        )
        chunks.append("---\n")

        chunks.append("## Tables\n")
        for t in tables:
            chunks.append(render_table_section(con, t, declared_fks))

        chunks.append("---\n")
        chunks.append(render_column_name_graph(graph))

        OUT_PATH.write_text("\n".join(chunks))
        print(f"Wrote {OUT_PATH}")
        print(f"  Tables: {len(tables)}")
        print(f"  Declared FKs: {sum(len(v) for v in declared_fks.values())}")
        print(f"  Shared columns (in 2+ tables): {len(graph)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()