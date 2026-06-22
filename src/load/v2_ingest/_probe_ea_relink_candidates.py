"""Read-only review list: EA-relink candidates for ea_id-NULL squad players.

For every squad outfielder with no ea_id (coverage `has_ea = false`), list EA
FC26 candidates FROM THE SAME NATION, ranked on club + birth-year + a TOKEN-AWARE
name score. Club is the key signal (resolve_squad_links deferred it as D5): a
nickname like 'Vinicius Junior' -> EA 'Vini Jr' loses on raw string similarity to
a same-nation namesake, but club ('Real Madrid') + birth year pin it. Token
scoring also lets vini~vinicius / jr~junior count as near-matches.

Writes ea_relink_review.csv (top-N candidates per player, with club/ovr/position
shown so you can eyeball-confirm, plus a blank `confirm` column). Confirmed rows
feed data/config/ea_id_overrides.json (next step). NO DB writes.

Run:  uv run python src/load/v2_ingest/_probe_ea_relink_candidates.py
"""
from __future__ import annotations
import csv
import difflib
import json
import re
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "processed" / "worldcup.duckdb"
OUT = ROOT / "ea_relink_review.csv"
REF_YEAR = 2026
TOPN = 5
# composite weights: club dominates, then name, then a birth-year bonus.
W_CLUB, W_NAME, W_YEAR = 0.50, 0.35, 0.15
STRONG = 0.80          # composite >= this AND year_ok -> auto-confident suggestion

EA_ALIASES = {
    "Holland": "NED", "Korea Republic": "KOR", "Republic of Korea": "KOR",
    "IR Iran": "IRN", "Czechia": "CZE", "Türkiye": "TUR", "Turkiye": "TUR",
    "Cape Verde Islands": "CPV", "Cabo Verde": "CPV",
    "Côte d'Ivoire": "CIV", "Cote d'Ivoire": "CIV", "Congo DR": "COD",
}
_CLUB_STOP = (" fc", " cf", " sc", " ac", " afc", " cd", " sad", " club", " calcio")


def _deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _tokens(s) -> list[str]:
    if not isinstance(s, str):
        return []
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", _deacc(s).lower()).split() if t]


def _normclub(s) -> str:
    if not isinstance(s, str):
        return ""
    c = re.sub(r"[^a-z0-9 ]", " ", _deacc(s).lower())
    for t in _CLUB_STOP:
        c = c.replace(t, " ")
    return re.sub(r"\s+", " ", c).strip()


def _tok_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _name_sim(qt: list[str], ct: list[str]) -> float:
    """Mean best-token match, symmetrised so extra tokens on either side don't
    dominate. Rewards nickname/sub-token overlap (vini~vinicius, jr~junior)."""
    if not qt or not ct:
        return 0.0
    fwd = sum(max(_tok_sim(a, b) for b in ct) for a in qt) / len(qt)
    rev = sum(max(_tok_sim(b, a) for a in qt) for b in ct) / len(ct)
    return (fwd + rev) / 2.0


def main() -> None:
    nm = json.loads((ROOT / "data" / "config" / "nation_codes.json").read_text("utf-8"))
    nm.pop("_comment", None)
    ea_name2code = {**nm, **EA_ALIASES}

    con = duckdb.connect(str(DB), read_only=True)
    sq = con.execute("""
        SELECT c.squad_row_id, c.nation_code, c.player_name, s.name_norm, s.club,
               c.coverage_tier, c.empirical_minutes_total AS emp_min, s.dob
        FROM player_coverage_index c
        JOIN wc2026_squad s ON s.squad_row_id = c.squad_row_id
        WHERE c.has_ea = FALSE AND c.primary_position_group <> 'GK'
    """).df()
    ea = con.execute("SELECT ea_id, name, name_norm, nation_name, club, ovr, "
                     "position, age FROM ea_fc26_player").df()
    con.close()

    ea["code"] = ea["nation_name"].map(ea_name2code)
    ea["byear"] = ea["age"].map(lambda a: REF_YEAR - int(a) if pd.notna(a) else None)
    ea["tok"] = ea["name"].map(_tokens)
    ea["nclub"] = ea["club"].map(_normclub)
    ea_by_nation: dict = {}
    for r in ea.itertuples():
        if pd.notna(r.code):
            ea_by_nation.setdefault(r.code, []).append(r)

    rows, no_pool = [], []
    tier_rank = {"empirical_unrated": 0, "ea_only": 1, "group_only": 2, "none": 3}
    sq = sq.sort_values(by=["coverage_tier", "nation_code"],
                        key=lambda s: s.map(tier_rank) if s.name == "coverage_tier" else s)

    for r in sq.itertuples():
        byear = int(pd.Timestamp(r.dob).year) if pd.notna(r.dob) else None
        pool = ea_by_nation.get(r.nation_code, [])
        if not pool:
            no_pool.append((r.nation_code, r.player_name, r.coverage_tier))
            continue
        qtok, qclub = _tokens(r.player_name), _normclub(r.club)
        scored = []
        for c in pool:
            nsim = _name_sim(qtok, c.tok)
            csim = difflib.SequenceMatcher(None, qclub, c.nclub).ratio() if qclub and c.nclub else 0.0
            yok = byear is not None and c.byear is not None and abs(byear - c.byear) <= 1
            comp = W_CLUB * csim + W_NAME * nsim + W_YEAR * (1.0 if yok else 0.0)
            scored.append((comp, csim, nsim, yok, c))
        scored.sort(key=lambda t: t[0], reverse=True)
        for rank, (comp, csim, nsim, yok, c) in enumerate(scored[:TOPN], 1):
            rows.append({
                "squad_row_id": r.squad_row_id, "nation": r.nation_code,
                "squad_name": r.player_name, "squad_club": r.club,
                "squad_byear": byear, "coverage_tier": r.coverage_tier,
                "emp_min": int(r.emp_min), "rank": rank,
                "cand_ea_id": int(c.ea_id), "cand_ea_name": c.name,
                "cand_club": c.club, "cand_ovr": int(c.ovr) if pd.notna(c.ovr) else None,
                "cand_pos": c.position, "cand_byear": c.byear,
                "composite": round(comp, 3), "club_sim": round(csim, 2),
                "name_sim": round(nsim, 2), "year_ok": int(yok),
                "suggest": "y" if (rank == 1 and yok and comp >= STRONG) else "",
                "confirm": "",
            })

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # proposed-overrides file: the auto-confident rank-1 picks only, human-readable
    # and keyed by squad_row_id, ready for you to veto/trim. Apply step reads ea_id.
    proposed = {
        "_comment": ("Proposed EA relinks (auto-confident: rank-1, year-corroborated, "
                     "composite>=%.2f). VERIFY then rename to ea_id_overrides.json. "
                     "Delete any wrong row; add high-value manual picks from "
                     "ea_relink_review.csv (set ea_id + src='manual')." % STRONG),
    }
    for x in rows:
        if x["suggest"] == "y":
            proposed[str(x["squad_row_id"])] = {
                "ea_id": x["cand_ea_id"], "squad": x["squad_name"],
                "ea": x["cand_ea_name"], "club": x["cand_club"],
                "ovr": x["cand_ovr"], "composite": x["composite"], "src": "auto",
            }
    PROPOSED = ROOT / "data" / "config" / "ea_id_overrides.proposed.json"
    PROPOSED.write_text(json.dumps(proposed, indent=2, ensure_ascii=False), "utf-8")

    players = {x["squad_row_id"] for x in rows}
    strong = [x for x in rows if x["rank"] == 1 and x["year_ok"] and x["composite"] >= STRONG]
    emp1 = [x for x in rows if x["rank"] == 1 and x["coverage_tier"] == "empirical_unrated"]
    print(f"unmatched outfielders: {len(players) + len(no_pool)} "
          f"(EA-nation pool: {len(players)}, no pool: {len(no_pool)})")
    print(f"auto-confident rank-1 (composite>={STRONG} & year_ok): {len(strong)}")
    print(f"-> wrote {OUT.name} ({len(rows)} rows, top {TOPN}/player)")
    print(f"-> wrote {PROPOSED.name} ({len(strong)} auto-confident picks to verify)\n")
    print(f"== empirical_unrated priority cases ({len(emp1)}) — squad -> best EA cand ==")
    for x in sorted(emp1, key=lambda v: -v["composite"]):
        flag = "OK" if (x["year_ok"] and x["composite"] >= STRONG) else "??"
        print(f"  [{flag}] {x['nation']} {x['squad_name']!r} / {x['squad_club']!r} "
              f"-> {x['cand_ea_name']!r} / {x['cand_club']!r} "
              f"(ovr {x['cand_ovr']}, {x['cand_pos']}, comp {x['composite']}, "
              f"club {x['club_sim']}, name {x['name_sim']})")
    if no_pool:
        print(f"\nno EA-nation pool ({len(no_pool)}) — not in EA, can't relink: "
              + ", ".join(f"{c} {n}" for c, n, _ in no_pool[:10])
              + (" ..." if len(no_pool) > 10 else ""))


if __name__ == "__main__":
    main()
