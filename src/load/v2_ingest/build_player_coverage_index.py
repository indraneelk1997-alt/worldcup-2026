"""Build `player_coverage_index` (docs/player_coverage_index.md).

One row per wc2026_squad player: identity + per-source coverage (Understat / FBref
/ StatsBomb minutes & matches) + a model-ready flag + a single coverage tier &
score. The reusable substrate for the dashboard "Squad coverage" page and future
player-profile / ratings visuals.

Derived rollup: CREATE OR REPLACE, no FK, never writes a source table (Claude.md
rule 9). Built read-only against the FULL DB (so StatsBomb minutes, whose source
event table is dropped from the trimmed DB, are computed once here); flows into
the trimmed dashboard DB via make_dashboard_db.py (exclusion copy auto-includes
it). Idempotent: rerun rebuilds the table.

Run:  uv run python src/load/v2_ingest/build_player_coverage_index.py
"""
from __future__ import annotations
import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(os.environ.get("WC2026_DB", ROOT / "data" / "processed" / "worldcup.duckdb"))

EMPIRICAL_FLOOR = 270        # minutes; matches item 9's eligibility floor
EMP_SOURCES = ["understat", "fbref", "statsbomb"]

# coverage_tier -> coverage_score (0..1). Tunable; documented in the design doc.
# 'gk' scores None -> excluded from the team-level mean (GKs are rated separately
# and have no adjusted-attrs row by design).
TIER_SCORE = {
    "empirical+rated":   1.0,
    "rated":             0.8,
    "empirical_unrated": 0.5,    # real minutes, but ea_id NULL -> not rateable
    "ea_only":           0.4,
    "group_only":        0.2,
    "none":              0.0,
    "gk":                None,
}


def _per_source(con) -> pd.DataFrame:
    """-> long rows (squad_row_id, source, minutes, matches) for the 3 empirical
    sources. Understat/FBref come from the player_match_all view via the id-union
    crosswalk (our_player_id is FBref's id space; Understat uses its own, so we
    also match players-table ids by normalised name -- same crosswalk as
    build_position_eligibility.py). StatsBomb is name-linked to the squad."""
    uf = con.execute("""
        WITH xref AS (
            SELECT squad_row_id, our_player_id AS pid FROM wc2026_squad
            WHERE our_player_id IS NOT NULL
            UNION
            SELECT s.squad_row_id, p.player_id AS pid
            FROM wc2026_squad s
            JOIN players p ON lower(strip_accents(p.player_name)) = s.name_norm
        )
        SELECT x.squad_row_id, pm.source,
               SUM(pm.minutes)            AS minutes,
               COUNT(DISTINCT pm.game_id) AS matches
        FROM xref x
        JOIN player_match_all pm ON pm.player_id = x.pid
        WHERE pm.minutes IS NOT NULL
        GROUP BY 1, 2
    """).df()

    sb = con.execute("""
        SELECT s.squad_row_id, 'statsbomb' AS source,
               SUM(spm.minutes)             AS minutes,
               COUNT(DISTINCT spm.match_id) AS matches
        FROM statsbomb_player_match spm
        JOIN wc2026_squad s
          ON lower(strip_accents(trim(s.player_name)))
           = lower(strip_accents(trim(spm.player)))
        WHERE spm.minutes IS NOT NULL
        GROUP BY 1
    """).df()

    return pd.concat([uf, sb], ignore_index=True)


def _tier(row) -> str:
    """One coverage label per player. has_adjusted (a player_adjusted_attributes_
    wide row) is the rateable/not-rateable dividing line."""
    if row.primary_position_group == "GK":
        return "gk"
    if row.has_adjusted:
        return "empirical+rated" if row.empirical_minutes_total >= EMPIRICAL_FLOOR else "rated"
    # not rateable -> classify by the best data we DO have
    if row.empirical_minutes_total >= EMPIRICAL_FLOOR:
        return "empirical_unrated"          # tracking data exists, but ea_id NULL
    if row.coverage_basis == "ea_fallback":
        return "ea_only"
    if row.coverage_basis == "group_fallback":
        return "group_only"
    return "none"


def build() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH))      # writable: builds its own table

    base = con.execute("""
        SELECT s.squad_row_id, s.nation_code, s.nation_name, s.player_name,
               s.name_norm, s.primary_position_group, s.position_class,
               s.ea_id, s.our_player_id, s.caps, s.shirt_no, s.club, s.dob,
               (ea.ea_id IS NOT NULL)  AS has_ea,
               (adj.squad_row_id IS NOT NULL) AS has_adjusted,
               elig.basis AS coverage_basis
        FROM wc2026_squad s
        LEFT JOIN ea_fc26_player ea ON ea.ea_id = s.ea_id
        LEFT JOIN (SELECT DISTINCT squad_row_id FROM player_adjusted_attributes_wide) adj
               ON adj.squad_row_id = s.squad_row_id
        LEFT JOIN (SELECT squad_row_id, MAX(basis) AS basis
                   FROM squad_position_eligibility GROUP BY 1) elig
               ON elig.squad_row_id = s.squad_row_id
    """).df()

    src = _per_source(con)

    # pivot per-source minutes & matches into wide columns (0 where absent)
    for metric in ("minutes", "matches"):
        wide = (src.pivot(index="squad_row_id", columns="source", values=metric)
                   .reindex(columns=EMP_SOURCES).fillna(0).astype(int))
        wide.columns = [f"{s}_{metric}" for s in wide.columns]
        base = base.merge(wide, left_on="squad_row_id", right_index=True, how="left")

    mins_cols = [f"{s}_minutes" for s in EMP_SOURCES]
    base[mins_cols] = base[mins_cols].fillna(0).astype(int)
    base[[f"{s}_matches" for s in EMP_SOURCES]] = \
        base[[f"{s}_matches" for s in EMP_SOURCES]].fillna(0).astype(int)
    base["empirical_minutes_total"] = base[mins_cols].sum(axis=1)
    base["n_empirical_sources"] = (base[mins_cols] > 0).sum(axis=1)

    base["coverage_tier"] = base.apply(_tier, axis=1)
    base["coverage_score"] = base["coverage_tier"].map(TIER_SCORE)

    df = base  # noqa: F841  (referenced by the DuckDB replacement scan below)
    con.execute("CREATE OR REPLACE TABLE player_coverage_index AS SELECT * FROM df")
    con.close()
    return base


def _report(df: pd.DataFrame) -> None:
    print(f"player_coverage_index: {len(df)} rows\n")
    print("tier distribution:")
    print(df["coverage_tier"].value_counts().to_string(), "\n")

    # team rating preview (GKs excluded from the score mean via NaN scores)
    g = df.groupby("nation_code")
    team = pd.DataFrame({
        "pct_model_ready": g["has_adjusted"].mean().mul(100).round(1),
        "weighted_score":  g["coverage_score"].mean().mul(100).round(1),
        "n": g.size(),
    }).sort_values("pct_model_ready")
    print("lowest-coverage nations:")
    print(team.head(6).to_string(), "\n")
    print("sample strong nations:")
    print(team.loc[team.index.isin(["BRA", "ARG", "NED", "SWE", "ESP", "ENG"])].to_string(), "\n")

    # the S43 dark-screen players -> should now be visibly flagged
    flag = df[df["squad_row_id"].isin([221, 585])][
        ["squad_row_id", "player_name", "nation_code", "primary_position_group",
         "ea_id", "empirical_minutes_total", "has_adjusted", "coverage_tier"]]
    print("S43 dark-screen players:")
    print(flag.to_string(index=False))


if __name__ == "__main__":
    _report(build())
