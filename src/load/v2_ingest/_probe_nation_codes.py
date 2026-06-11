"""
_probe_nation_codes.py — S23 probe (deletable). Validate
data/config/nation_codes.json against (1) the 48 parsed WC2026 nations and
(2) the nation codes already in our DB.

Two-way cross-check catches a wrong code without needing name<->code truth
in our data:
  * a WC nation whose mapped code is ABSENT from our data -> either no
    overlap (fine for a minnow) or a wrong code (suspicious for a nation
    that surely has top-5/UCL players).
  * an our-data code claimed by NO WC nation -> non-WC nation (fine) OR the
    real code for a WC nation we mis-mapped (e.g. 'RSA' present but South
    Africa mapped to 'ZAF').
Eyeball the two lists together. Read-only DB -> safe during the UCL fetch.

    uv run python src/load/v2_ingest/_probe_nation_codes.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from ingest_wc2026_squads import fetch, parse_squads, URL  # noqa: E402

MAP_PATH = Path("data/config/nation_codes.json")
DB_PATH = "data/processed/worldcup.duckdb"
REPORT = Path("data/raw/wc2026/_probe_nation_codes_report.txt")


def main() -> int:
    lines: list[str] = []
    summary: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    rc = 0
    try:
        nmap = {k: v for k, v in json.loads(MAP_PATH.read_text()).items()
                if not k.startswith("_")}
        rows, _ = parse_squads(fetch(URL))
        wc_nations = sorted({r["nation_name"] for r in rows})

        # 1. completeness: every parsed nation mapped?
        unmapped = [n for n in wc_nations if n not in nmap]
        w(f"WC nations parsed: {len(wc_nations)} | mapped: "
          f"{len(wc_nations) - len(unmapped)} | UNMAPPED: {unmapped}")

        # 2. cross-check vs DB codes (read-only)
        con = duckdb.connect(DB_PATH, read_only=True)
        our_codes = set(con.sql(
            "SELECT DISTINCT nation FROM player_match_fbref WHERE nation IS NOT NULL"
        ).df()["nation"])
        con.close()

        wc_codes = {nmap[n] for n in wc_nations if n in nmap}
        in_db = sorted([n for n in wc_nations if nmap.get(n) in our_codes])
        not_in_db = sorted([n for n in wc_nations if nmap.get(n) not in our_codes])
        orphan_db = sorted(our_codes - wc_codes)

        w(f"\nWC nations whose code IS in our DB ({len(in_db)}): "
          + ", ".join(f"{n}={nmap[n]}" for n in in_db))
        w(f"\nWC nations whose code is NOT in our DB ({len(not_in_db)}) "
          f"-- check minnow-vs-wrong-code:")
        for n in not_in_db:
            w(f"    {n:28} -> {nmap.get(n)}")
        w(f"\nDB codes claimed by NO WC nation ({len(orphan_db)}) "
          f"-- scan for a real WC code we mis-mapped:")
        w("    " + " ".join(orphan_db))

        summary.append(f"unmapped={len(unmapped)} in_db={len(in_db)} "
                       f"not_in_db={len(not_in_db)} db_orphans={len(orphan_db)}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("nation-code probe done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
