#!/usr/bin/env python3
"""
Validate the item-5 PlayStyle -> family map (data/config/playstyle_families.json)
against the LIVE EA data (ea_fc26_playstyle). Read-only.

Checks (rule 4 -- the check runs in the real context, so any typo fails loudly):
  1. every distinct EA playstyle is covered by exactly one family (no uncovered)
  2. no phantom config tag absent from the data (catches misspellings)
  3. every family reference resolves to a defined family
Exit 0 = PASS, 1 = FAIL. Run from repo root.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "data" / "config" / "playstyle_families.json"
DB = REPO / "data" / "processed" / "worldcup.duckdb"


def main():
    cfg = json.loads(CONFIG.read_text())
    p2f = cfg["playstyle_to_family"]
    families = set(cfg["families"])
    cfg_tags = set(p2f)

    con = duckdb.connect(str(DB), read_only=True)
    db_tags = {r[0] for r in con.execute(
        "SELECT DISTINCT playstyle FROM ea_fc26_playstyle").fetchall()}

    uncovered = db_tags - cfg_tags          # in data, missing from config
    phantom = cfg_tags - db_tags            # in config, missing from data (typo?)
    bad_fam = {t: f for t, f in p2f.items() if f not in families}

    print(f"DB distinct tags : {len(db_tags)}")
    print(f"config tags      : {len(cfg_tags)}")
    print(f"families defined : {len(families)}  ({', '.join(sorted(families))})")
    print("per-family counts:", dict(sorted(Counter(p2f.values()).items())))
    if uncovered:
        print("UNCOVERED (in DB, not in config):", sorted(uncovered))
    if phantom:
        print("PHANTOM (in config, not in DB):", sorted(phantom))
    if bad_fam:
        print("BAD FAMILY REF:", bad_fam)

    ok = not (uncovered or phantom or bad_fam)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
