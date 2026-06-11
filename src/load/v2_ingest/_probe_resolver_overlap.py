"""
_probe_resolver_overlap.py — S24 probe (deletable). Size the resolver problem
BEFORE designing match logic: how well does wc2026_squad overlap with
ea_fc26_player (the prior) and players (empirical), by name_norm, and how
much ambiguity / dob-confirmation is there.

Read-only. Measures, decides nothing. Writes a report.

    uv run python src/load/v2_ingest/_probe_resolver_overlap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "data/processed/worldcup.duckdb"
REPORT = Path("data/raw/wc2026/_probe_resolver_overlap.txt")


def buckets(s: pd.Series) -> dict:
    return {"0": int((s == 0).sum()), "1": int((s == 1).sum()),
            ">1": int((s > 1).sum())}


def main() -> int:
    lines: list[str] = []
    summary: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    rc = 0
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        squad = con.sql(
            "SELECT squad_row_id, name_norm, nation_code, dob, club FROM wc2026_squad"
        ).df()
        ea = con.sql(
            "SELECT ea_id, name_norm, nation_name, club FROM ea_fc26_player"
        ).df()
        # players has no stored name_norm — normalise on the fly, same recipe.
        players = con.sql(
            "SELECT player_id, lower(strip_accents(player_name)) AS name_norm, "
            "player_dob FROM players"
        ).df()
        con.close()

        ea_counts = ea.groupby("name_norm").size()
        pl_counts = players.groupby("name_norm").size()
        squad["n_ea"] = squad["name_norm"].map(ea_counts).fillna(0).astype(int)
        squad["n_pl"] = squad["name_norm"].map(pl_counts).fillna(0).astype(int)

        # dob-confirmable empirical match: a players row with same name_norm AND dob
        pl_dob = (players.dropna(subset=["player_dob"])
                  .groupby("name_norm")["player_dob"].apply(set).to_dict())
        squad["dob_confirm"] = squad.apply(
            lambda r: r["dob"] in pl_dob.get(r["name_norm"], set()), axis=1)

        n = len(squad)
        w(f"squad rows: {n}")
        w(f"\nEA prior match (by name_norm): {buckets(squad['n_ea'])}")
        w(f"  -> any EA candidate: {int((squad['n_ea']>0).sum())}/{n} "
          f"({100*(squad['n_ea']>0).mean():.1f}%)")
        w(f"  -> AMBIGUOUS (>1 EA, needs nation/club/age tiebreak): "
          f"{int((squad['n_ea']>1).sum())}")
        w(f"\nEmpirical match (by name_norm vs players): {buckets(squad['n_pl'])}")
        w(f"  -> any empirical candidate: {int((squad['n_pl']>0).sum())}/{n} "
          f"({100*(squad['n_pl']>0).mean():.1f}%)")
        w(f"  -> dob-CONFIRMED (name_norm + exact dob): "
          f"{int(squad['dob_confirm'].sum())}")
        w(f"  -> name-only ambiguous (>1 players): {int((squad['n_pl']>1).sum())}")

        # 4-way coverage matrix — the number that decides the coverage strategy
        both = int(((squad["n_ea"] > 0) & (squad["n_pl"] > 0)).sum())
        ea_only = int(((squad["n_ea"] > 0) & (squad["n_pl"] == 0)).sum())
        emp_only = int(((squad["n_ea"] == 0) & (squad["n_pl"] > 0)).sum())
        neither = int(((squad["n_ea"] == 0) & (squad["n_pl"] == 0)).sum())
        w("\nCOVERAGE MATRIX (squad players by source, exact name_norm):")
        w(f"  both EA + empirical : {both}")
        w(f"  EA only             : {ea_only}")
        w(f"  empirical only      : {emp_only}")
        w(f"  NEITHER (dark)      : {neither}   <-- truly 0-coverage on exact match")

        # is the EA gap recoverable (spelling/name-order) or genuine absence?
        ea_surn = set(ea["name_norm"].str.split().str[-1])
        sq_no_ea = squad[squad["n_ea"] == 0].copy()
        sq_no_ea["surname"] = sq_no_ea["name_norm"].str.split().str[-1]
        recov = int(sq_no_ea["surname"].isin(ea_surn).sum())
        w(f"\nEA gap recoverability ({len(sq_no_ea)} no-exact-match):")
        w(f"  share a surname with some EA player (likely name-form, recoverable): {recov}")
        w(f"  no surname match anywhere in EA (likely genuinely absent):         {len(sq_no_ea)-recov}")

        dark_by_nat = (squad[(squad["n_ea"] == 0) & (squad["n_pl"] == 0)]
                       .groupby("nation_code").size().sort_values(ascending=False).head(12))
        w("\ndarkest nations (NEITHER source), top 12:")
        w("  " + ", ".join(f"{nat}:{c}" for nat, c in dark_by_nat.items()))
        summary.append(f"both={both} ea_only={ea_only} emp_only={emp_only} "
                       f"neither={neither} ea_surname_recov={recov}")

        # show a few ambiguous EA names + the nations that would disambiguate
        amb = squad[squad["n_ea"] > 1]["name_norm"].drop_duplicates().head(8)
        w("\nsample AMBIGUOUS EA names (nation/club should split these):")
        for nm in amb:
            cand = ea[ea["name_norm"] == nm][["nation_name", "club"]]
            w(f"  {nm!r}: " + " | ".join(
                f"{r.nation_name}/{r.club}" for r in cand.itertuples()))

        # squad players with NO EA match at all (truly uncovered)
        none_ea = squad[squad["n_ea"] == 0][["name_norm", "nation_code"]].head(10)
        w(f"\nsquad players with NO EA match ({int((squad['n_ea']==0).sum())}); sample:")
        for r in none_ea.itertuples():
            w(f"  {r.name_norm!r} [{r.nation_code}]")

        summary.append(
            f"squad={n} ea_any={int((squad['n_ea']>0).sum())} "
            f"ea_ambig={int((squad['n_ea']>1).sum())} "
            f"empirical_any={int((squad['n_pl']>0).sum())} "
            f"dob_confirmed={int(squad['dob_confirm'].sum())}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("resolver-overlap probe done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
