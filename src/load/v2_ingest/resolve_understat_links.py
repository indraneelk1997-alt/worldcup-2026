"""resolve_understat_links.py — S45. Persist a `wc2026_squad.understat_player_id`
so the blend engine can pull Understat (attack/possession) data by ID instead of
by hardened name.

Why this exists (docs/understat_relink.md): the engine
(`_probe_adjusted_ratings.build`) matched Understat by hardened name, which silently
dropped attack/possession data for any player whose Understat name differs from the
squad name (Mbappé→"Mbappe-Lottin", word-order, middle names, transliteration).
Understat rows carry no nation/dob, so this resolver links by:

  understat_player_id = (verified override)  ELSE  (UNIQUE hardened-name match)

The override map (data/config/understat_id_overrides.json) is the human-verified,
club-corroborated relink set (built by _probe_understat_relink.py). The fallback
reproduces the engine's *current* behaviour exactly — `hard(lower(strip_accents
(name)))`, accepted only when a single Understat player_id owns that hardened name
— so switching the engine to the column loses NO existing link. Rows where several
Understat ids share one hardened name (the engine used to SUM them by name) resolve
to NULL and are reported; switch only if that count is ~0.

Separate module (not folded into resolve_squad_links.py) on purpose: that resolver
disambiguates by nation+birth-year; Understat has neither and corroborates by club,
so the two matching philosophies stay apart.

    uv run python src/load/v2_ingest/resolve_understat_links.py            # dry-run
    uv run python src/load/v2_ingest/resolve_understat_links.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

DB = "data/processed/worldcup.duckdb"
OVERRIDES = Path("data/config/understat_id_overrides.json")


def hard(s) -> str:
    """Match the engine's normaliser exactly (_probe_adjusted_ratings.hard)."""
    return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else ""


def main(apply: bool) -> int:
    con = duckdb.connect(DB, read_only=not apply)

    squad = con.execute("SELECT squad_row_id, name_norm FROM wc2026_squad").df()
    # Understat universe: one row per player_id that actually has match rows.
    us = con.execute("""
        SELECT DISTINCT pl.player_id, lower(strip_accents(pl.player_name)) AS nn
        FROM player_match_stats p JOIN players pl ON p.player_id = pl.player_id
    """).df()
    us["h"] = us["nn"].map(hard)
    by_h: dict[str, list[int]] = {}
    for r in us.itertuples():
        by_h.setdefault(r.h, []).append(int(r.player_id))

    ov = {}
    if OVERRIDES.exists():
        raw = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        ov = {int(k): int(v["understat_player_id"])
              for k, v in raw.items() if not k.startswith("_")}

    rows, n_ov, n_name, n_multi, n_none = [], 0, 0, 0, 0
    for r in squad.itertuples():
        srid = int(r.squad_row_id)
        if srid in ov:
            uid, method = ov[srid], "override"
            n_ov += 1
        else:
            ids = by_h.get(hard(r.name_norm), [])
            if len(ids) == 1:
                uid, method = ids[0], "name"
                n_name += 1
            elif len(ids) > 1:
                uid, method = None, "multi"      # engine summed these by name
                n_multi += 1
            else:
                uid, method = None, "none"
                n_none += 1
        rows.append({"squad_row_id": srid, "understat_player_id": uid, "method": method})
    res = pd.DataFrame(rows)

    print("=" * 64)
    print(f"  Understat resolver — {'APPLY' if apply else 'DRY-RUN'} — squad rows: {len(res)}")
    print("=" * 64)
    print(f"  override : {n_ov}")
    print(f"  name     : {n_name}")
    print(f"  multi    : {n_multi}   (>1 Understat id share the hardened name — "
          f"engine used to sum; resolve to NULL)")
    print(f"  none     : {n_none}   (not in Understat — correct for non-big-5)")
    print(f"  -> understat_player_id filled: {int(res['understat_player_id'].notna().sum())}/{len(res)}")
    if n_multi:
        mm = res[res["method"] == "multi"].merge(squad, on="squad_row_id")
        print("\n  multi-id hardnames (eyeball — would lose summed data if any matter):")
        for r in mm.head(15).itertuples():
            print(f"    {r.squad_row_id}  {r.name_norm!r}")

    if not apply:
        print("\nDRY-RUN — no writes. Re-run with --apply.")
        con.close()
        return 0

    cols = [c[0] for c in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='wc2026_squad'").fetchall()]
    if "understat_player_id" not in cols:
        con.execute("ALTER TABLE wc2026_squad ADD COLUMN understat_player_id BIGINT")
    con.register("upd", res[["squad_row_id", "understat_player_id"]])
    con.execute("""
        UPDATE wc2026_squad t SET understat_player_id = u.understat_player_id
        FROM upd u WHERE t.squad_row_id = u.squad_row_id""")
    con.unregister("upd")
    print("\nAPPLIED understat_player_id. Re-run dry-run to confirm stable counts.")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    sys.exit(main(apply=ap.parse_args().apply))
