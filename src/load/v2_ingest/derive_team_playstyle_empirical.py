"""
derive_team_playstyle_empirical.py
----------------------------------
Derive the EMPIRICAL leg of the D2 team-playstyle vector from StatsBomb open
event data, one row per (team, tournament). Full design + citations:
docs/playstyle_empirical_design.md.

Five axes (each stored raw + percentile-rank normalised across the
team-tournament pool; normalised so 1 = the HIGH end of the axis label):
  1 directness  = median pass distance + share-forward   (combined post-norm)
  2 width       = share of pass/carry starts in wing channels
  3 line_height = median x of back-line players' defensive engagements
  4 ppda        = opp completed passes in own 60% / team def-actions in that 60%
                  (norm INVERTED: 1 = most intense press)
  5 possession  = team pass-share in its matches

Coordinate frame (confirmed S31, not assumed): StatsBomb normalises every event
to the acting team attacking +x (own goal x=0, pitch 120x80); no halftime flip,
so per-team x aggregation is valid as-is.

DERIVED table: --apply does a wholesale CREATE OR REPLACE rebuild (idempotent,
self-contained on StatsBomb IDs -> no FK exposure). Dry-run prints, writes nothing.

Run from repo root:
  uv run python src/load/v2_ingest/derive_team_playstyle_empirical.py          # dry-run
  uv run python src/load/v2_ingest/derive_team_playstyle_empirical.py --apply  # write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "data" / "config" / "playstyle_metrics.json"
DB_PATH = REPO_ROOT / "data" / "processed" / "worldcup.duckdb"

KEYS = ["competition_id", "season_id", "team_id", "team"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def tournament_filter(cfg: dict) -> str:
    """WHERE clause restricting to the configured (competition, season) pairs."""
    parts = [
        f"(competition_id={t['competition_id']} AND season_id={t['season_id']})"
        for t in cfg["tournaments"]
    ]
    return "(" + " OR ".join(parts) + ")"


def sql_list(items: list[str]) -> str:
    return ", ".join("'" + i.replace("'", "''") + "'" for i in items)


def build(con: duckdb.DuckDBPyConnection, cfg: dict) -> pd.DataFrame:
    tf = tournament_filter(cfg)
    zone = cfg["ppda_zone"]
    wing = cfg["wing_channels"]
    eng = sql_list(cfg["line_height"]["engagement_types"])
    backsub = cfg["line_height"]["back_line_position_substr"]
    ppda_types = sql_list(cfg["ppda_def_action_types"])

    # --- sample size (feeds lambda_team confidence downstream) ---
    n_matches = con.sql(f"""
        SELECT competition_id, season_id, team_id, team,
               COUNT(DISTINCT match_id) AS n_matches
        FROM statsbomb_event WHERE {tf}
        GROUP BY 1,2,3,4
    """).df()

    # --- 1 directness: median pass distance + share forward ---
    directness = con.sql(f"""
        SELECT competition_id, season_id, team_id, team,
               MEDIAN(SQRT(POWER(end_x-x,2)+POWER(end_y-y,2))) AS pass_dist_med_raw,
               AVG(CASE WHEN end_x > x THEN 1.0 ELSE 0.0 END)   AS fwd_share_raw
        FROM statsbomb_event
        WHERE {tf} AND type='Pass' AND x IS NOT NULL AND end_x IS NOT NULL
        GROUP BY 1,2,3,4
    """).df()

    # --- 2 width: wing-channel share of pass+carry starts, ATTACKING HALF only ---
    #   x>=attacking_half_min_x so central buildup doesn't dilute attacking width.
    width = con.sql(f"""
        SELECT competition_id, season_id, team_id, team,
               AVG(CASE WHEN y<={wing['left_max_y']} OR y>={wing['right_min_y']}
                        THEN 1.0 ELSE 0.0 END) AS width_raw
        FROM statsbomb_event
        WHERE {tf} AND type IN ('Pass','Carry') AND y IS NOT NULL
          AND x >= {wing['attacking_half_min_x']}
        GROUP BY 1,2,3,4
    """).df()

    # --- 3 line height: median x of back-line defensive engagements ---
    line = con.sql(f"""
        SELECT competition_id, season_id, team_id, team,
               MEDIAN(x) AS line_height_raw,
               COUNT(*)  AS line_height_n
        FROM statsbomb_event
        WHERE {tf} AND x IS NOT NULL
          AND position LIKE '%{backsub}%'
          AND type IN ({eng})
        GROUP BY 1,2,3,4
    """).df()

    # --- 4 PPDA: opp completed passes in own 60% / team def-actions in that 60% ---
    #   dacts = pressing team's actions in attacking 60% (tackle-filtered Duels)
    #   cpass = each team's completed passes in own 60%; opponent = other team in match
    ppda = con.sql(f"""
        WITH dacts AS (
            SELECT competition_id, season_id, team_id, team, match_id, COUNT(*) AS acts
            FROM statsbomb_event
            WHERE {tf} AND x >= {zone['def_action_min_x']}
              AND ( type IN ({ppda_types})
                    OR (type='Duel'
                        AND json_extract_string(raw,'$.duel.type.name')='Tackle') )
            GROUP BY 1,2,3,4,5
        ),
        cpass AS (
            SELECT team_id, match_id, COUNT(*) AS cpass
            FROM statsbomb_event
            WHERE {tf} AND type='Pass' AND outcome IS NULL
              AND x <= {zone['opp_pass_max_x']}
            GROUP BY 1,2
        )
        SELECT d.competition_id, d.season_id, d.team_id, d.team,
               SUM(c.cpass)::DOUBLE / NULLIF(SUM(d.acts),0) AS ppda_raw
        FROM dacts d
        JOIN cpass c ON c.match_id=d.match_id AND c.team_id <> d.team_id
        GROUP BY 1,2,3,4
    """).df()

    # --- 5 possession: team pass-share across its matches ---
    possession = con.sql(f"""
        WITH pc AS (
            SELECT competition_id, season_id, team_id, team, match_id, COUNT(*) AS p
            FROM statsbomb_event WHERE {tf} AND type='Pass'
            GROUP BY 1,2,3,4,5
        ),
        tot AS (SELECT match_id, SUM(p) AS tp FROM pc GROUP BY 1)
        SELECT pc.competition_id, pc.season_id, pc.team_id, pc.team,
               SUM(pc.p)::DOUBLE / SUM(tot.tp) AS possession_raw
        FROM pc JOIN tot ON pc.match_id=tot.match_id
        GROUP BY 1,2,3,4
    """).df()

    # --- merge all metrics onto the team-tournament spine ---
    df = n_matches
    for part in (directness, width, line, ppda, possession):
        df = df.merge(part, on=KEYS, how="left")

    # --- normalise: percentile-rank across the whole pool; 1 = high end ---
    def pr(s: pd.Series) -> pd.Series:
        return s.rank(pct=True, method="average")

    df["directness_norm"] = (pr(df["pass_dist_med_raw"]) + pr(df["fwd_share_raw"])) / 2.0
    df["width_norm"] = pr(df["width_raw"])
    df["line_height_norm"] = pr(df["line_height_raw"])
    df["ppda_norm"] = pr(-df["ppda_raw"])  # inverted: low PPDA = intense press = ~1
    df["possession_norm"] = pr(df["possession_raw"])

    df["model_version"] = cfg.get("model_version", "playstyle_empirical_v1")
    df["created_at"] = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return df.sort_values(["competition_id", "season_id", "team"]).reset_index(drop=True)


def report(df: pd.DataFrame) -> None:
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    n_tourn = df[["competition_id", "season_id"]].drop_duplicates().shape[0]
    print(f"\nteam_playstyle_empirical — {len(df)} rows across {n_tourn} tournaments\n")
    print(df.groupby(["competition_id", "season_id"]).size().rename("teams").to_string())

    cols = ["team", "n_matches", "directness_norm", "width_norm",
            "line_height_norm", "ppda_norm", "possession_norm"]
    show = df[cols].copy()
    for c in cols[2:]:
        show[c] = show[c].round(2)
    print("\n--- full table (normalised 0-1) ---")
    print(show.to_string(index=False))

    print("\n--- sanity: highest defensive line ---")
    print(df.nlargest(6, "line_height_norm")[
        ["team", "line_height_raw", "line_height_norm"]].round(2).to_string(index=False))
    print("\n--- sanity: most intense press (lowest raw PPDA) ---")
    print(df.nsmallest(6, "ppda_raw")[
        ["team", "ppda_raw", "ppda_norm"]].round(2).to_string(index=False))
    nan_ppda = int(df["ppda_raw"].isna().sum())
    if nan_ppda:
        print(f"\n[warn] {nan_ppda} team(s) have NULL PPDA (no def-actions in zone) — inspect")


def apply(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    con.register("playstyle_df", df)
    con.execute(
        "CREATE OR REPLACE TABLE team_playstyle_empirical AS SELECT * FROM playstyle_df"
    )
    con.unregister("playstyle_df")
    n = con.sql("SELECT COUNT(*) FROM team_playstyle_empirical").fetchone()[0]
    print(f"\n[ok] wrote team_playstyle_empirical ({n} rows)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Derive empirical team-playstyle vectors.")
    ap.add_argument("--apply", action="store_true",
                    help="write the table (default: dry-run, writes nothing)")
    args = ap.parse_args()

    cfg = load_config()
    con = duckdb.connect(str(DB_PATH), read_only=not args.apply)
    try:
        df = build(con, cfg)
        report(df)
        if args.apply:
            apply(con, df)
        else:
            print("\n(dry-run — nothing written; re-run with --apply to persist)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
