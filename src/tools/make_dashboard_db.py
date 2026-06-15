#!/usr/bin/env python3
"""
make_dashboard_db.py -- build a trimmed, runtime-only copy of the DuckDB for the
dashboard, small enough to share with friends.

Strategy (docs/dashboard_design.md S5 / S40): trim by EXCLUSION, not inclusion.
The full DB is ~950 MB, almost all of it three StatsBomb RAW tables
(statsbomb_frame 5.8M rows, statsbomb_event 686k, statsbomb_frame_meta 368k).
Those are pure upstream derivation inputs -- everything the dashboard reads from
them is already baked into the derived tables (occupancy_base, zone_xt,
team_playstyle_*). So we copy EVERY table except those three. That covers the
whole dashboard read-set for V0->V3 up front (no per-version re-trimming); a
future version that genuinely needs event-level data is a deliberate add.

We use CREATE TABLE AS SELECT, which copies data only (no PK/FK/CHECK/indexes).
That's exactly right for a read-only dashboard DB -- and it sidesteps every
DuckDB FK/constraint gotcha (see Claude.md) for free.

Run (read-only on the source; writes a NEW file, never touches the full DB):
  uv run python src/tools/make_dashboard_db.py
  uv run python src/tools/make_dashboard_db.py --out /tmp/wc_dash.duckdb

Then verify the dashboard against it without clobbering your full DB:
  WC2026_DB=data/processed/worldcup_dashboard.duckdb uv run streamlit run dashboard/app.py
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
SRC_DEFAULT = REPO / "data" / "processed" / "worldcup.duckdb"
OUT_DEFAULT = REPO / "data" / "processed" / "worldcup_dashboard.duckdb"

# The only tables we drop: StatsBomb raw event/frame data (upstream-only, huge).
EXCLUDE = {"statsbomb_frame", "statsbomb_event", "statsbomb_frame_meta"}


def build(src: Path, out: Path) -> None:
    if not src.exists():
        raise SystemExit(f"source DB not found: {src}")
    if out.exists():
        out.unlink()                       # fresh file => smallest, no fragmentation

    con = duckdb.connect(str(out))          # writable destination
    con.execute(f"ATTACH '{src}' AS src (READ_ONLY)")

    all_tables = [r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() "
        "WHERE database_name='src' ORDER BY table_name").fetchall()]
    keep = [t for t in all_tables if t not in EXCLUDE]
    skip = [t for t in all_tables if t in EXCLUDE]

    print(f"source: {src}  ({len(all_tables)} tables)")
    print(f"excluding {len(skip)}: {', '.join(sorted(skip)) or '(none)'}\n")

    copied = []
    for t in keep:
        con.execute(f'CREATE TABLE "{t}" AS SELECT * FROM src."{t}"')
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        copied.append((t, n))

    con.execute("DETACH src")
    con.execute("CHECKPOINT")               # flush to disk before we measure size
    con.close()

    for t, n in sorted(copied, key=lambda r: -r[1]):
        print(f"  {n:>10,}  {t}")
    size_mb = os.path.getsize(out) / 1e6
    print(f"\ncopied {len(copied)} tables -> {out}")
    print(f"trimmed size: {size_mb:.1f} MB   (full DB ~950 MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the trimmed dashboard DuckDB.")
    ap.add_argument("--src", type=Path, default=SRC_DEFAULT, help="full source DB")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT, help="trimmed output DB")
    a = ap.parse_args()
    build(a.src, a.out)


if __name__ == "__main__":
    main()
