"""
S26 — resolve wc2026_squad -> EA prior (ea_id) + empirical (our_player_id).

Implements docs/resolver_design.md (D1-D5) against observed shapes. Fills the
link columns already on wc2026_squad via a re-runnable UPDATE-by-squad_row_id
(idempotent; never touches roster rows). StatsBomb xref + club aliases DEFERRED
(D2/D5).

Model:
  candidate-generate by name_norm, then disambiguate by birth-YEAR + nation
  (D4). Corroborator = birth year (exact from a real dob; +-1 from EA's integer
  age). Discrete-tier confidence (D3). Nation MISMATCH on an otherwise-good
  name match -> reject (better dark than wrong). Guarded fuzzy fallback (D1):
  fuzzy candidates drawn from WITHIN the squad player's nation, so nation
  corroboration is automatic.

Default DRY-RUN: prints the method/confidence/coverage distribution + samples,
NO writes. Pass --apply to UPDATE.

    uv run python src/load/v2_ingest/resolve_squad_links.py            # dry-run
    uv run python src/load/v2_ingest/resolve_squad_links.py --apply    # write
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys

import duckdb
import pandas as pd

DB_PATH = "data/processed/worldcup.duckdb"
REF_YEAR = 2026               # WC2026; EA age is ~as-of 2025-26 -> +-1 tolerance
FUZZY_CUTOFF = 0.85

# EA carries full nation_name with its own spellings; overlay on nation_codes.json.
# (Verified S26: covers all 47 EA-representable squad nations; QAT absent from EA.)
EA_ALIASES = {
    "Holland": "NED",
    "Korea Republic": "KOR", "Republic of Korea": "KOR",
    "IR Iran": "IRN",
    "Czechia": "CZE",
    "Türkiye": "TUR", "Turkiye": "TUR",
    "Cape Verde Islands": "CPV", "Cabo Verde": "CPV",
    "Côte d'Ivoire": "CIV", "Cote d'Ivoire": "CIV",
    "Congo DR": "COD",
}

CONF = {
    "exact+nation+year": 0.95,
    "exact+year": 0.90,
    "exact+nation": 0.85,
    "exact": 0.55,
    "fuzzy+nation+year": 0.65,
    "fuzzy+nation": 0.50,
    "none": None,
}


def _ea_year_ok(byear, age) -> bool:
    """EA gives integer age (~as-of 2025-26). Compare implied birth year +-1."""
    if byear is None or age is None or pd.isna(age):
        return False
    return abs(int(byear) - (REF_YEAR - int(age))) <= 1


# ---------------------------------------------------------------- EA ladder
def match_ea(name, code, byear, ea_by_name, ea_by_nation, fuzzy):
    cands = ea_by_name.get(name, [])
    if not cands:  # 0 exact
        if not fuzzy:
            return None, "none", None
        # guarded fuzzy WITHIN nation (auto nation-corroborated)
        pool = ea_by_nation.get(code, [])
        names = [p[0] for p in pool]
        m = difflib.get_close_matches(name, names, n=1, cutoff=FUZZY_CUTOFF)
        if not m:
            return None, "none", None
        c = next(p for p in pool if p[0] == m[0])  # (name, ea_id, age)
        meth = "fuzzy+nation+year" if _ea_year_ok(byear, c[2]) else "fuzzy+nation"
        return c[1], meth, m[0]

    if len(cands) == 1:  # (ea_id, code, age)
        eid, ccode, age = cands[0]
        if ccode != code:                      # nation mismatch (incl. None) -> reject
            return None, "none", None
        return eid, ("exact+nation+year" if _ea_year_ok(byear, age) else "exact+nation"), name

    # >1 exact -> disambiguate by nation, then year (club skipped, D5)
    nat = [c for c in cands if c[1] == code]
    if len(nat) == 1:
        eid, _, age = nat[0]
        return eid, ("exact+nation+year" if _ea_year_ok(byear, age) else "exact+nation"), name
    if len(nat) > 1:
        aged = [c for c in nat if _ea_year_ok(byear, c[2])]
        if len(aged) == 1:
            return aged[0][0], "exact+nation+year", name
    return None, "none", None


# --------------------------------------------------------- empirical ladder
def match_emp(name, code, byear, pl_by_name, fbref_nat, pl_fbref_by_nation, fuzzy):
    cands = pl_by_name.get(name, [])  # list of (player_id, dob_year|None)
    if not cands:  # 0 exact
        if not fuzzy:
            return None, "none", None
        # guarded fuzzy within FBref-subset of nation
        pool = pl_fbref_by_nation.get(code, [])  # (name, player_id, dob_year)
        names = [p[0] for p in pool]
        m = difflib.get_close_matches(name, names, n=1, cutoff=FUZZY_CUTOFF)
        if not m:
            return None, "none", None
        c = next(p for p in pool if p[0] == m[0])
        meth = "fuzzy+nation+year" if (byear and c[2] == byear) else "fuzzy+nation"
        return c[1], meth, m[0]

    fb = [c for c in cands if c[1] is not None]   # FBref subset (has dob year)
    us = [c for c in cands if c[1] is None]        # Understat subset (no dob/nation)

    good = []
    for pid, dy in fb:
        if byear and dy == byear:                  # year must agree
            nat = fbref_nat.get(pid)
            if nat == code:
                good.append((pid, "exact+nation+year"))
            elif nat is None:
                good.append((pid, "exact+year"))
            # nat mismatch -> drop this candidate (reject)
    if len(good) == 1:
        return good[0][0], good[0][1], name
    if len(good) > 1:
        nm = [g for g in good if g[1] == "exact+nation+year"]
        return (nm[0][0], nm[0][1], name) if len(nm) == 1 else (None, "none", None)

    # no FBref year-match -> unique Understat name accepts low (D4/B)
    if not fb and len(us) == 1:
        return us[0][0], "exact", name
    return None, "none", None


def main(apply: bool, fuzzy: bool) -> int:
    import json
    from pathlib import Path
    nm = json.loads(Path("data/config/nation_codes.json").read_text(encoding="utf-8"))
    nm.pop("_comment", None)
    ea_name2code = {**nm, **EA_ALIASES}

    con = duckdb.connect(DB_PATH, read_only=not apply)
    squad = con.sql(
        "SELECT squad_row_id, name_norm, nation_code, dob FROM wc2026_squad").df()
    ea = con.sql("SELECT ea_id, name_norm, nation_name, age FROM ea_fc26_player").df()
    players = con.sql(
        "SELECT player_id, lower(strip_accents(player_name)) AS name_norm, "
        "player_dob FROM players").df()
    fb = con.sql(
        "SELECT player_id, nation, count(*) c FROM player_match_fbref "
        "WHERE nation IS NOT NULL GROUP BY 1,2").df()

    # D1 (revised S26 on dry-run evidence): strip ALL non-alphanumerics so
    # spacing/hyphen/stray-diacritic variants collapse to EXACT
    # (son heung-min == son heung min; akaydın == akayd n). Safer than fuzzy,
    # which wrongly merged same-nation same-age names (kim jin/min gyu;
    # mohamed alaa -> salah). Applied identically to all three sources.
    def hardnorm(s):
        return re.sub(r"[^a-z0-9]", "", s) if isinstance(s, str) else s
    for _df in (squad, ea, players):
        _df["name_norm"] = _df["name_norm"].map(hardnorm)

    # --- lookup structures ---
    ea["code"] = ea["nation_name"].map(ea_name2code)
    ea_by_name: dict = {}
    ea_by_nation: dict = {}
    for r in ea.itertuples():
        ea_by_name.setdefault(r.name_norm, []).append((r.ea_id, r.code, r.age))
        if pd.notna(r.code):
            ea_by_nation.setdefault(r.code, []).append((r.name_norm, r.ea_id, r.age))

    players["dob_year"] = players["player_dob"].apply(
        lambda d: int(pd.Timestamp(d).year) if pd.notna(d) else None)
    # most-frequent FBref nation per player
    fbref_nat = (fb.sort_values("c").groupby("player_id")["nation"].last().to_dict())
    pl_by_name: dict = {}
    for r in players.itertuples():
        pl_by_name.setdefault(r.name_norm, []).append((r.player_id, r.dob_year))
    pl_fbref_by_nation: dict = {}
    for r in players.itertuples():
        if r.dob_year is None:
            continue
        nat = fbref_nat.get(r.player_id)
        if nat:
            pl_fbref_by_nation.setdefault(nat, []).append(
                (r.name_norm, r.player_id, r.dob_year))

    # --- resolve every squad row ---
    rows = []
    for r in squad.itertuples():
        byear = int(pd.Timestamp(r.dob).year) if pd.notna(r.dob) else None
        ea_id, ea_m, ea_match = match_ea(r.name_norm, r.nation_code, byear,
                                         ea_by_name, ea_by_nation, fuzzy)
        pl_id, pl_m, pl_match = match_emp(r.name_norm, r.nation_code, byear,
                                          pl_by_name, fbref_nat, pl_fbref_by_nation,
                                          fuzzy)
        rows.append({
            "squad_row_id": r.squad_row_id, "name_norm": r.name_norm,
            "nation_code": r.nation_code,
            "ea_id": int(ea_id) if ea_id is not None else None,
            "ea_link_method": ea_m, "ea_link_confidence": CONF[ea_m],
            "ea_match": ea_match,
            "our_player_id": int(pl_id) if pl_id is not None else None,
            "link_method": pl_m, "link_confidence": CONF[pl_m],
            "pl_match": pl_match,
        })
    res = pd.DataFrame(rows)

    # --- report ---
    n = len(res)
    has_ea = res["ea_id"].notna()
    has_pl = res["our_player_id"].notna()
    print("=" * 68)
    print(f"  Resolver — {'APPLY' if apply else 'DRY-RUN'} — squad rows: {n}")
    print("=" * 68)
    print("\nEA link methods:")
    print(res["ea_link_method"].value_counts().to_string())
    print(f"  -> ea_id filled: {int(has_ea.sum())}/{n}")
    print("\nEmpirical link methods:")
    print(res["link_method"].value_counts().to_string())
    print(f"  -> our_player_id filled: {int(has_pl.sum())}/{n}")
    print("\nCoverage (resolved):")
    print(f"  both={int((has_ea & has_pl).sum())}  ea_only={int((has_ea & ~has_pl).sum())}"
          f"  emp_only={int((~has_ea & has_pl).sum())}  dark={int((~has_ea & ~has_pl).sum())}")
    print("\nfuzzy EA matches (eyeball — squad -> EA):")
    for r in res[res["ea_link_method"].str.startswith("fuzzy")].head(10).itertuples():
        print(f"   {r.name_norm!r} [{r.nation_code}] -> {r.ea_match!r}")
    print("\nfuzzy empirical matches (eyeball — squad -> players):")
    for r in res[res["link_method"].str.startswith("fuzzy")].head(10).itertuples():
        print(f"   {r.name_norm!r} [{r.nation_code}] -> {r.pl_match!r}")
    print("\naccept-low Understat (exact 0.55, no corroboration) sample:")
    for r in res[res["link_method"] == "exact"].head(8).itertuples():
        print(f"   {r.name_norm!r} [{r.nation_code}]")

    if apply:
        upd = res[["squad_row_id", "ea_id", "ea_link_method", "ea_link_confidence",
                   "our_player_id", "link_method", "link_confidence"]].copy()
        # store 'none' method as NULL (no link) for cleanliness
        upd.loc[upd["ea_link_method"] == "none", "ea_link_method"] = None
        upd.loc[upd["link_method"] == "none", "link_method"] = None
        con.register("upd", upd)
        con.execute("""
            UPDATE wc2026_squad t SET
              ea_id = u.ea_id,
              ea_link_method = u.ea_link_method,
              ea_link_confidence = u.ea_link_confidence,
              our_player_id = u.our_player_id,
              link_method = u.link_method,
              link_confidence = u.link_confidence
            FROM upd u WHERE t.squad_row_id = u.squad_row_id
        """)
        con.unregister("upd")
        print("\nAPPLIED. Re-run (dry-run) to confirm stable distribution.")
    else:
        print("\nDRY-RUN — no writes. Re-run with --apply.")
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--fuzzy", action="store_true",
                    help="enable guarded fuzzy fallback (default OFF — it mis-merges "
                         "same-nation same-age names; see resolver_design.md D1)")
    args = ap.parse_args()
    sys.exit(main(apply=args.apply, fuzzy=args.fuzzy))
