"""Validate data/config/position_source_map.json against reality (item 9).

Checks, per the design doc (docs/item9_xi_selection.md):
  1. Every position value actually present in each source (player_match_all for
     understat/fbref, statsbomb_event for statsbomb) is mapped -- nothing the
     data emits is silently dropped, except the explicit `drop` list.
  2. Every mapped `code` exists in the canonical `positions` table.
  3. Every mapped `role` is in the declared role taxonomy.
  4. Every `flank` is one of C/L/R; cb_lean (if present) is L/R.

Read-only. Standalone (no package imports) so it runs either as a path or a
module. Needs statsbomb_event -> point at the FULL DB, not the trimmed one.

Run:  uv run python src/load/v2_ingest/validate_position_map.py
Exit code 0 = PASS, 1 = FAIL (so it can gate a build step).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
CFG_PATH = ROOT / "data" / "config" / "position_source_map.json"
DB_PATH = Path(os.environ.get("WC2026_DB", ROOT / "data" / "processed" / "worldcup.duckdb"))

FLANKS = {"C", "L", "R"}
LEANS = {"L", "R"}


def fbref_first_token(pos: str) -> str:
    """FBref tags a multi-position match 'POS1,POS2'; we map the primary (first)."""
    return pos.split(",")[0].strip()


def observed_vocab(con) -> dict[str, set[str]]:
    """Distinct raw position strings actually present, per source."""
    out: dict[str, set[str]] = {"understat": set(), "fbref": set(), "statsbomb": set()}
    for src in ("understat", "fbref"):
        rows = con.execute(
            "SELECT DISTINCT position FROM player_match_all "
            "WHERE source = ? AND position IS NOT NULL", [src]).fetchall()
        for (p,) in rows:
            out[src].add(fbref_first_token(p) if src == "fbref" else p)
    sb = con.execute(
        "SELECT DISTINCT position FROM statsbomb_event WHERE position IS NOT NULL"
    ).fetchall()
    out["statsbomb"] = {p for (p,) in sb}
    return out


def main() -> int:
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    roles = set(cfg["roles"])
    drop = set(cfg["drop"])

    con = duckdb.connect(str(DB_PATH), read_only=True)
    canon_codes = {c for (c,) in con.execute(
        "SELECT position_code FROM positions").fetchall()}
    observed = observed_vocab(con)
    con.close()

    failures: list[str] = []
    print(f"DB: {DB_PATH}")
    print(f"canonical codes ({len(canon_codes)}): {', '.join(sorted(canon_codes))}")
    print(f"roles ({len(roles)}): {', '.join(cfg['roles'])}\n")

    # --- check 1: coverage of observed vocab, per source ---
    for src in ("understat", "fbref", "statsbomb"):
        smap = cfg[src]
        obs = observed[src]
        unmapped = sorted(c for c in obs if c not in smap and c not in drop)
        mapped_n = len([c for c in obs if c in smap])
        total_n = len([c for c in obs if c not in drop])
        status = "OK" if not unmapped else "FAIL"
        print(f"[{status}] {src}: {mapped_n}/{total_n} observed codes mapped"
              + (f"  (dropped: {sorted(c for c in obs if c in drop)})"
                 if obs & drop else ""))
        if unmapped:
            failures.append(f"{src}: UNMAPPED observed codes -> {unmapped}")
        # extra keys in the map not present in data (warn only)
        extra = sorted(k for k in smap if k not in obs and not k.startswith("_"))
        if extra:
            print(f"       note: map has {len(extra)} codes not seen in data "
                  f"(harmless): {extra}")

    # --- checks 2-4: every mapping entry is internally valid ---
    print()
    bad_code, bad_role, bad_flank = [], [], []
    for src in ("understat", "fbref", "statsbomb"):
        for raw, m in cfg[src].items():
            if raw.startswith("_"):
                continue
            if m["code"] not in canon_codes:
                bad_code.append(f"{src}:{raw}->{m['code']}")
            if m["role"] not in roles:
                bad_role.append(f"{src}:{raw}->{m['role']}")
            if m.get("flank") not in FLANKS:
                bad_flank.append(f"{src}:{raw}->flank={m.get('flank')}")
            if "cb_lean" in m and m["cb_lean"] not in LEANS:
                bad_flank.append(f"{src}:{raw}->cb_lean={m['cb_lean']}")
    for label, bad in (("code not in positions table", bad_code),
                       ("role not in taxonomy", bad_role),
                       ("bad flank/cb_lean", bad_flank)):
        print(f"[{'OK' if not bad else 'FAIL'}] {label}: {len(bad)} bad")
        if bad:
            failures.append(f"{label}: {bad}")

    print()
    if failures:
        print("VALIDATION FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("VALIDATION PASSED ✓  every observed source code maps to a valid "
          "canonical code + role.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
