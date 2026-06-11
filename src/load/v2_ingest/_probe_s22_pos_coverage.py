"""
S22 follow-up probe — the ONE fact the first probe missed (leaf() bug):
the full distinct FBref player-match `pos` set, and which values are NOT
already in our `positions` table. This decides decision (d).

Read-only DB; FBref from cache (~6s reparse, no network).

Run:
    uv run python src/load/v2_ingest/_probe_s22_pos_coverage.py
"""

from __future__ import annotations

import duckdb
import pandas as pd
from soccerdata import FBref

DB_PATH = "data/processed/worldcup.duckdb"
LEAGUE = "UEFA-Champions League"
SEASON = "2024-2025"

pm = FBref(leagues=[LEAGUE], seasons=SEASON).read_player_match_stats(
    stat_type="summary"
)

# 'pos' is the ('pos','') column -> select by first level
pos_series = pm[("pos", "")] if ("pos", "") in pm.columns else pm["pos"]
pos_vals = sorted(pos_series.dropna().astype(str).unique())

print("\n=== distinct FBref player-match `pos` values ===")
print(f"  count: {len(pos_vals)}")
print(f"  values: {pos_vals}")

# any multi-position (comma) values?
multi = [v for v in pos_vals if "," in v]
print(f"\n  multi-position (comma) values: {multi or 'NONE'}")

# coverage vs positions table
con = duckdb.connect(DB_PATH, read_only=True)
existing = {r[0] for r in con.execute(
    "SELECT position_code FROM positions"
).fetchall()}
con.close()

# split comma values into tokens for coverage check
tokens = set()
for v in pos_vals:
    for tok in v.split(","):
        tokens.add(tok.strip())

missing = sorted(tokens - existing)
present = sorted(tokens & existing)
print(f"\n  tokens present in positions table ({len(present)}): {present}")
print(f"  tokens MISSING from positions table ({len(missing)}): {missing}")

# age sample (confirm 'YY-DDD')
age_series = pm[("age", "")] if ("age", "") in pm.columns else pm["age"]
print(f"\n  age samples: {age_series.dropna().astype(str).head(6).tolist()}")
