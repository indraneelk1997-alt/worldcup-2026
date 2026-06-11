"""
ingest_ea_fc26.py — EA Sports FC 26 attribute ingest (coverage solver / prior).

Source = Kaggle flynn28/eafc26-player-database, EAFC26.csv (design + dataset
comparison in docs/data_sourcing.md item (b)). Built section-by-section:

  * Section P (done):  read CSV, filter men, parse -> player rows +
                        exploded PlayStyles.
  * Section M (done):  CREATE ea_fc26_player + ea_fc26_playstyle.
  * Section I (done):  INSERT OR IGNORE both (DuckDB INSERT BY NAME).
  * (later) EA<->squad / EA<->players resolver feeds wc2026_squad.ea_id.

nation_code is deferred (EA's country spellings differ from Wikipedia's —
'Korea Republic' vs 'South Korea', 'Holland' vs 'Netherlands'; reconciled in
the resolver step, not here). The table has the column but it stays NULL now.

    uv run python src/load/v2_ingest/ingest_ea_fc26.py            # dry-run, no DB
    uv run python src/load/v2_ingest/ingest_ea_fc26.py --apply    # create + insert
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

CSV_PATH = Path("data/raw/eafc26/eafc26-player-database/EAFC26.csv")
REPORT = Path("data/raw/eafc26/_parse_ea_report.txt")
DB_PATH = "data/processed/worldcup.duckdb"

# Section M — DDL (design in docs/data_sourcing.md item b). ea_id is EA's own
# ID -> natural PK, so INSERT OR IGNORE on it = idempotent (no sequence needed).
DDL_PLAYER = """
CREATE TABLE IF NOT EXISTS ea_fc26_player (
  ea_id INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL,
  name_norm VARCHAR,
  ovr INTEGER,
  position VARCHAR,
  position_class VARCHAR,
  alt_positions VARCHAR,
  nation_name VARCHAR,
  nation_code VARCHAR,                       -- deferred (resolver); NULL for now
  league VARCHAR,
  club VARCHAR,
  age INTEGER,
  preferred_foot VARCHAR,
  weak_foot INTEGER,
  skill_moves INTEGER,
  height_cm INTEGER,
  weight_kg INTEGER,
  ea_pace INTEGER, ea_shooting INTEGER, ea_passing INTEGER,
  ea_dribbling INTEGER, ea_defending INTEGER, ea_physical INTEGER,
  acceleration INTEGER, sprint_speed INTEGER, positioning INTEGER,
  finishing INTEGER, shot_power INTEGER, long_shots INTEGER, volleys INTEGER,
  penalties INTEGER, vision INTEGER, crossing INTEGER, free_kick_accuracy INTEGER,
  short_passing INTEGER, long_passing INTEGER, curve INTEGER, dribbling INTEGER,
  agility INTEGER, balance INTEGER, reactions INTEGER, ball_control INTEGER,
  composure INTEGER, interceptions INTEGER, heading_accuracy INTEGER,
  def_awareness INTEGER, standing_tackle INTEGER, sliding_tackle INTEGER,
  jumping INTEGER, stamina INTEGER, strength INTEGER, aggression INTEGER,
  gk_diving INTEGER, gk_handling INTEGER, gk_kicking INTEGER,
  gk_positioning INTEGER, gk_reflexes INTEGER,
  play_style_raw VARCHAR,
  source_url VARCHAR,
  card_url VARCHAR,
  source VARCHAR DEFAULT 'eafc26',
  ingested_at TIMESTAMP DEFAULT now()
);
"""
DDL_PLAYSTYLE = """
CREATE TABLE IF NOT EXISTS ea_fc26_playstyle (
  ea_id     INTEGER NOT NULL,
  playstyle VARCHAR NOT NULL,
  tier      VARCHAR NOT NULL,       -- base / plus  (no plus_plus observed)
  PRIMARY KEY (ea_id, playstyle)
);
"""

# EA position code -> our position_class (12 codes, all map; probe S23).
POS_CLASS = {
    "GK": "GK",
    "CB": "DEF", "LB": "DEF", "RB": "DEF",
    "CDM": "MID", "CM": "MID", "CAM": "MID", "LM": "MID", "RM": "MID",
    "LW": "FWD", "RW": "FWD", "ST": "FWD",
}

# 6 family scores get an ea_ prefix to avoid colliding with same-named
# sub-attributes (Dribbling family vs the Dribbling sub-attribute).
FAMILY = {"PAC": "ea_pace", "SHO": "ea_shooting", "PAS": "ea_passing",
          "DRI": "ea_dribbling", "DEF": "ea_defending", "PHY": "ea_physical"}

# Straight CSV-col -> snake_case renames (sub-attrs, GK, meta).
RENAME = {
    "ID": "ea_id", "Name": "name", "OVR": "ovr", "Position": "position",
    "Alternative positions": "alt_positions", "Age": "age",
    "Nation": "nation_name", "League": "league", "Team": "club",
    "Preferred foot": "preferred_foot", "Weak foot": "weak_foot",
    "Skill moves": "skill_moves", "url": "source_url", "card": "card_url",
    # sub-attributes
    "Acceleration": "acceleration", "Sprint Speed": "sprint_speed",
    "Positioning": "positioning", "Finishing": "finishing",
    "Shot Power": "shot_power", "Long Shots": "long_shots", "Volleys": "volleys",
    "Penalties": "penalties", "Vision": "vision", "Crossing": "crossing",
    "Free Kick Accuracy": "free_kick_accuracy", "Short Passing": "short_passing",
    "Long Passing": "long_passing", "Curve": "curve", "Dribbling": "dribbling",
    "Agility": "agility", "Balance": "balance", "Reactions": "reactions",
    "Ball Control": "ball_control", "Composure": "composure",
    "Interceptions": "interceptions", "Heading Accuracy": "heading_accuracy",
    "Def Awareness": "def_awareness", "Standing Tackle": "standing_tackle",
    "Sliding Tackle": "sliding_tackle", "Jumping": "jumping",
    "Stamina": "stamina", "Strength": "strength", "Aggression": "aggression",
    # goalkeeper (NaN for outfield)
    "GK Diving": "gk_diving", "GK Handling": "gk_handling",
    "GK Kicking": "gk_kicking", "GK Positioning": "gk_positioning",
    "GK Reflexes": "gk_reflexes",
}

_LEADING_INT = re.compile(r"(\d+)")


def _norm_name(name) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _lead_int(v):
    """'175cm / 5\\'9\"' -> 175 ; '72kg / 159lb' -> 72 ; NaN-safe."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    m = _LEADING_INT.search(str(v))
    return int(m.group(1)) if m else None


def explode_playstyles(ea_id: int, raw) -> list[dict]:
    """"['Finesse Shot+', 'First Touch']" -> rows with base name + tier.
    Tier = count of trailing '+': 0 base, 1 'plus', 2 'plus_plus'."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    try:
        items = ast.literal_eval(str(raw))
    except (ValueError, SyntaxError):
        return []
    out = []
    for tok in items:
        s = str(tok).strip()
        n_plus = len(s) - len(s.rstrip("+"))
        base = s.rstrip("+").strip()
        tier = {0: "base", 1: "plus", 2: "plus_plus"}.get(n_plus, "plus_plus")
        out.append({"ea_id": ea_id, "playstyle": base, "tier": tier})
    return out


def parse_ea(csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Return (players_df, playstyles_df, anomalies). Men only."""
    raw = pd.read_csv(csv_path)
    anomalies: list[str] = []
    men = raw[raw["GENDER"] == "M"].copy()

    out = pd.DataFrame()
    for src, dst in RENAME.items():
        if src not in men.columns:
            anomalies.append(f"missing expected column: {src!r}")
            continue
        out[dst] = men[src].values
    for src, dst in FAMILY.items():
        out[dst] = men[src].values

    out["name_norm"] = out["name"].map(_norm_name)
    out["position_class"] = out["position"].map(lambda p: POS_CLASS.get(str(p), "?"))
    out["height_cm"] = men["Height"].map(_lead_int).values
    out["weight_kg"] = men["Weight"].map(_lead_int).values
    out["play_style_raw"] = men["play style"].values

    bad_pos = sorted(set(out.loc[out["position_class"] == "?", "position"]))
    if bad_pos:
        anomalies.append(f"unmapped EA positions: {bad_pos}")

    ps_rows: list[dict] = []
    for ea_id, raw_ps in zip(out["ea_id"], out["play_style_raw"]):
        ps_rows.extend(explode_playstyles(int(ea_id), raw_ps))
    playstyles = pd.DataFrame(ps_rows)

    return out, playstyles, anomalies


def apply_section_mi(con, pdf: pd.DataFrame, sdf: pd.DataFrame) -> dict:
    """Section M (create) + Section I (insert). DuckDB INSERT BY NAME matches
    df columns to table columns by name; columns absent from the df (nation_code,
    source, ingested_at) take their table DEFAULT/NULL. Idempotent via PK."""
    con.execute(DDL_PLAYER)
    con.execute(DDL_PLAYSTYLE)
    p0 = con.execute("SELECT COUNT(*) FROM ea_fc26_player").fetchone()[0]
    s0 = con.execute("SELECT COUNT(*) FROM ea_fc26_playstyle").fetchone()[0]
    con.register("pdf_v", pdf)
    con.register("sdf_v", sdf)
    con.execute("INSERT OR IGNORE INTO ea_fc26_player BY NAME SELECT * FROM pdf_v")
    con.execute("INSERT OR IGNORE INTO ea_fc26_playstyle BY NAME SELECT * FROM sdf_v")
    p1 = con.execute("SELECT COUNT(*) FROM ea_fc26_player").fetchone()[0]
    s1 = con.execute("SELECT COUNT(*) FROM ea_fc26_playstyle").fetchone()[0]
    return {"players_ins": p1 - p0, "players_total": p1,
            "ps_ins": s1 - s0, "ps_total": s1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="execute writes (default: dry-run, no DB)")
    args = ap.parse_args()

    lines: list[str] = []
    summary: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    rc = 0
    try:
        if not CSV_PATH.exists():
            raise FileNotFoundError(f"{CSV_PATH} — download via kaggle (item b)")
        pdf, sdf, anomalies = parse_ea(CSV_PATH)

        w(f"men player rows: {len(pdf)}")
        w(f"ea_id unique: {pdf['ea_id'].is_unique}")
        w(f"position_class dist: {pdf['position_class'].value_counts().to_dict()}")
        w(f"ovr range: {pdf['ovr'].min()}-{pdf['ovr'].max()}")
        w(f"height_cm parsed: {pdf['height_cm'].notna().sum()}/{len(pdf)}"
          f" | weight_kg parsed: {pdf['weight_kg'].notna().sum()}/{len(pdf)}")
        gk = (pdf["position_class"] == "GK").sum()
        w(f"GK players: {gk} | gk_diving non-null: {pdf['gk_diving'].notna().sum()}")
        w(f"distinct leagues: {pdf['league'].nunique()} | "
          f"distinct nations (EA spelling): {pdf['nation_name'].nunique()}")

        w(f"\nplaystyle child rows: {len(sdf)}")
        if len(sdf):
            w(f"distinct base playstyles: {sdf['playstyle'].nunique()}")
            w(f"tier dist: {sdf['tier'].value_counts().to_dict()}")
            w("top 12 playstyles: "
              + str(sdf['playstyle'].value_counts().head(12).to_dict()))

        w(f"\nanomalies: {len(anomalies)}")
        for a in anomalies:
            w("  " + a)

        w("\nsample players:")
        sc = ["ea_id", "name", "name_norm", "position", "position_class",
              "ovr", "ea_pace", "ea_dribbling", "dribbling", "nation_name",
              "club", "age", "height_cm", "weight_kg"]
        w(pdf[sc].head(6).to_string(index=False))
        w("\nsample playstyle rows:")
        w(sdf.head(10).to_string(index=False) if len(sdf) else "  (none)")

        # fail loud before any write
        assert not anomalies, f"{len(anomalies)} parse anomalies — fix before apply"
        assert pdf["ea_id"].is_unique, "ea_id not unique"

        if args.apply:
            con = duckdb.connect(DB_PATH, read_only=False)
            try:
                c = apply_section_mi(con, pdf, sdf)
            finally:
                con.close()
            w(f"\nSection M+I APPLIED: players inserted={c['players_ins']} "
              f"total={c['players_total']} | playstyles inserted={c['ps_ins']} "
              f"total={c['ps_total']}")
            summary.append(f"APPLIED players={c['players_total']} "
                           f"playstyles={c['ps_total']}")
        else:
            w(f"\n[DRY-RUN] would CREATE ea_fc26_player + ea_fc26_playstyle, "
              f"INSERT OR IGNORE {len(pdf)} players + {len(sdf)} playstyles")
            summary.append(f"DRY-RUN players={len(pdf)} playstyles={len(sdf)} "
                           f"anomalies={len(anomalies)}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("EA parse dry-run done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
