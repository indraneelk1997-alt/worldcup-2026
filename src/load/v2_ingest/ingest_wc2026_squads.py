"""
ingest_wc2026_squads.py — WC2026 squad roster loader (dashboard anchor).

Source = English Wikipedia "2026 FIFA World Cup squads" (design + rationale
in docs/data_sourcing.md item (a)). Built section-by-section, like
ingest_fbref.py:

  * Section P (done):  fetch + parse Wikipedia -> clean roster rows.
  * Section M (done):  CREATE SEQUENCE + wc2026_squad (locked DDL).
  * Section I (done):  INSERT OR IGNORE roster rows (nation_code attached).
  * Section R (TODO):  resolver pass -> our_player_id + ea_id.

nation_code comes from data/config/nation_codes.json (validated S23 by
_probe_nation_codes.py). Resolver/link columns (our_player_id, ea_id, ...)
are left NULL here and filled by Section R later.

    uv run python src/load/v2_ingest/ingest_wc2026_squads.py            # dry-run, no DB
    uv run python src/load/v2_ingest/ingest_wc2026_squads.py --apply    # create + insert
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from dateutil import parser as dateparser

URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
UA = "worldcup-2026-research/0.1 (contact: indraneelk1997@gmail.com)"
REPORT = Path("data/raw/wc2026/_parse_squads_report.txt")
DB_PATH = "data/processed/worldcup.duckdb"
NATION_MAP_PATH = Path("data/config/nation_codes.json")

# Section M — locked DDL (design in docs/data_sourcing.md item a). Standalone,
# additive; surrogate PK via sequence; natural-key UNIQUE for idempotency.
DDL_SEQUENCE = "CREATE SEQUENCE IF NOT EXISTS seq_wc2026_squad_row START 1;"
DDL_TABLE = """
CREATE TABLE IF NOT EXISTS wc2026_squad (
  squad_row_id    INTEGER  PRIMARY KEY DEFAULT nextval('seq_wc2026_squad_row'),
  nation_name     VARCHAR  NOT NULL,
  nation_code     VARCHAR,
  player_name     VARCHAR  NOT NULL,
  name_norm       VARCHAR  NOT NULL,
  dob             DATE,
  club            VARCHAR,
  position_class  VARCHAR  NOT NULL,
  shirt_no        INTEGER,
  caps            INTEGER,
  intl_goals      INTEGER,
  is_captain      BOOLEAN  DEFAULT FALSE,
  our_player_id   INTEGER,
  link_method     VARCHAR,
  link_confidence DOUBLE,
  ea_id           INTEGER,
  ea_link_method  VARCHAR,
  ea_link_confidence DOUBLE,
  source          VARCHAR  DEFAULT 'wikipedia',
  source_url      VARCHAR,
  ingested_at     TIMESTAMP DEFAULT now(),
  UNIQUE (nation_name, name_norm, dob)
);
"""
# Section I — omitted columns take their DEFAULT (squad_row_id=nextval,
# source='wikipedia', ingested_at=now()) or NULL (resolver/link cols).
SQUAD_INSERT = """
INSERT OR IGNORE INTO wc2026_squad
  (nation_name, nation_code, player_name, name_norm, dob, club,
   position_class, shirt_no, caps, intl_goals, is_captain, source_url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# The exact squad-table schema. A wikitable is a squad table iff its columns
# match this — drops the page's club/league summary tables (probe S23 found
# 51 'squad-like' vs 48 real, the extras being summaries with a 'Player' col).
SQUAD_COLS = ["No.", "Pos.", "Player", "Date of birth (age)", "Caps", "Goals", "Club"]

POS_CLASS = {"GK": "GK", "DF": "DEF", "MF": "MID", "FW": "FWD"}

# mirrors ingest_fbref._norm_name (kept local to avoid importing that module's
# heavy soccerdata.FBref import; TODO later: extract to a shared _textnorm.py).
def _norm_name(name) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


_CAPTAIN_RE = re.compile(r"\s*\((?:vice[- ]?)?captain\)\s*$", re.I)
_AGED_RE = re.compile(r"\s*\(aged.*?\)\s*$", re.I)


def parse_player_name(raw: str) -> tuple[str, bool]:
    """'Ronwen Williams(captain)' -> ('Ronwen Williams', True). Vice-captain
    is stripped too but does NOT set is_captain."""
    s = str(raw).strip()
    is_captain = bool(re.search(r"\(captain\)", s, re.I))
    return _CAPTAIN_RE.sub("", s).strip(), is_captain


def parse_dob(raw: str) -> date:
    """DoB cell -> date. Wikipedia mixes formats on the same page
    ('May 17, 2000' US and '8 October 1997' intl), so use dateutil rather
    than a fixed strptime. dayfirst=True disambiguates the intl form;
    month-name dates are unambiguous either way. Fail loud on drift."""
    s = _AGED_RE.sub("", str(raw)).strip()
    return dateparser.parse(s, dayfirst=True).date()


def _opt_int(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return int(float(s)) if s and s.lower() != "nan" else None


def parse_squads(html: str) -> tuple[list[dict], list[str]]:
    """Return (rows, anomalies). rows = one dict per squad player."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    anomalies: list[str] = []

    for tbl in soup.select("table.wikitable"):
        try:
            df = pd.read_html(io.StringIO(str(tbl)))[0]
        except ValueError:
            continue
        if list(df.columns) != SQUAD_COLS:
            continue  # not a squad table (summary/other)

        h3 = tbl.find_previous("h3")
        span = h3.find("span", class_="mw-headline") if h3 else None
        nation = (span.get_text() if span else (h3.get_text() if h3 else "?")).strip()

        for _, r in df.iterrows():
            try:
                name, is_capt = parse_player_name(r["Player"])
                dob = parse_dob(r["Date of birth (age)"])
                pos_raw = str(r["Pos."]).strip()
                rows.append({
                    "nation_name": nation,
                    "player_name": name,
                    "name_norm": _norm_name(name),
                    "dob": dob,
                    "club": str(r["Club"]).strip(),
                    "pos_raw": pos_raw,
                    "position_class": POS_CLASS.get(pos_raw, "?"),
                    "shirt_no": _opt_int(r["No."]),
                    "caps": _opt_int(r["Caps"]),
                    "intl_goals": _opt_int(r["Goals"]),
                    "is_captain": is_capt,
                })
                if pos_raw not in POS_CLASS:
                    anomalies.append(f"{nation}: unknown Pos. {pos_raw!r} ({name})")
            except Exception as e:  # fail loud per row, keep going
                anomalies.append(f"{nation}: row parse error {e} :: {dict(r)}")
    return rows, anomalies


def load_nation_map() -> dict:
    return {k: v for k, v in json.loads(NATION_MAP_PATH.read_text()).items()
            if not k.startswith("_")}


def apply_section_mi(con, rows: list[dict]) -> dict:
    """Section M (create seq+table) + Section I (INSERT OR IGNORE).

    Idempotent: re-run inserts 0 via the natural-key UNIQUE. Note: an ignored
    row still consumes a sequence value, so squad_row_id can have gaps on
    re-runs — harmless for a surrogate key. Returns {before, after, inserted}.
    """
    con.execute(DDL_SEQUENCE)
    con.execute(DDL_TABLE)
    before = con.execute("SELECT COUNT(*) FROM wc2026_squad").fetchone()[0]
    con.executemany(SQUAD_INSERT, [
        (r["nation_name"], r["nation_code"], r["player_name"], r["name_norm"],
         r["dob"], r["club"], r["position_class"], r["shirt_no"], r["caps"],
         r["intl_goals"], r["is_captain"], URL)
        for r in rows
    ])
    after = con.execute("SELECT COUNT(*) FROM wc2026_squad").fetchone()[0]
    return {"before": before, "after": after, "inserted": after - before}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="execute writes (default: dry-run, no DB)")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"

    lines: list[str] = []
    summary: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    rc = 0
    try:
        nmap = load_nation_map()
        rows, anomalies = parse_squads(fetch(URL))
        missing_code = sorted({r["nation_name"] for r in rows
                               if r["nation_name"] not in nmap})
        for r in rows:
            r["nation_code"] = nmap.get(r["nation_name"])

        df = pd.DataFrame(rows)
        nations = sorted(df["nation_name"].unique())
        per_nation = df.groupby("nation_name").size().sort_values()

        w(f"mode: {mode}")
        w(f"total squad rows: {len(df)}")
        w(f"distinct nations: {len(nations)}  (expect 48)")
        w(f"nation_code attached: {df['nation_code'].notna().sum()}/{len(df)}"
          f"  | unmapped: {missing_code}")
        w(f"position_class dist: {df['position_class'].value_counts().to_dict()}")
        w(f"captains flagged: {int(df['is_captain'].sum())}")
        w(f"anomalies: {len(anomalies)}")
        for a in anomalies[:40]:
            w("  " + a)

        w("\nper-nation squad sizes (expect 23-26 each):")
        for nat, n in per_nation.items():
            flag = "" if 23 <= n <= 26 else "  <-- OUT OF RANGE"
            w(f"  {nat:28} [{nmap.get(nat, '??')}] {n}{flag}")

        w("\nsample rows:")
        cols = ["nation_name", "nation_code", "player_name", "name_norm",
                "dob", "club", "position_class", "shirt_no", "is_captain"]
        w(df[cols].head(6).to_string(index=False))

        # Fail loud BEFORE any write (S14/S16 discipline).
        assert not missing_code, f"unmapped nations: {missing_code}"
        assert not anomalies, f"{len(anomalies)} parse anomalies — fix before apply"

        if args.apply:
            con = duckdb.connect(DB_PATH, read_only=False)
            try:
                c = apply_section_mi(con, rows)
            finally:
                con.close()
            w(f"\nSection M+I APPLIED: before={c['before']} after={c['after']} "
              f"inserted={c['inserted']}")
            summary.append(f"APPLIED inserted={c['inserted']} total={c['after']}")
        else:
            w(f"\n[DRY-RUN] would CREATE wc2026_squad + INSERT OR IGNORE "
              f"{len(df)} rows (re-run with --apply)")
            summary.append(f"DRY-RUN rows={len(df)} nations={len(nations)}/48 "
                           f"anomalies={len(anomalies)}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"squad ingest ({mode}) done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
