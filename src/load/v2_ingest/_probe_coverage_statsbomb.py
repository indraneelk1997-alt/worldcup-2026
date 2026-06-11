"""
_probe_coverage_statsbomb.py — S26 probe (deletable). Re-measure WC2026-squad
coverage now that StatsBomb Open (4 intl tournaments, 1718 players) is loaded.

EXTENDS _probe_resolver_overlap.py (S24) with a THIRD source axis: StatsBomb.
StatsBomb sits in its own ID space (the sidecar never minted into `players`),
so a plain re-run of the S24 probe can't see it. Here we match wc2026_squad
against the distinct StatsBomb players directly.

Match key = name_norm (+ nation). StatsBomb's `team` IS the national team, so
unlike Understat we get nation for free -> a name+nation strict match, with a
name-only loose match as the upper bound. StatsBomb team spellings may differ
from Wikipedia's; we map via nation_codes.json + an alias layer, and REPORT
any unmapped team (observe-don't-infer: trust the printed gaps, not the map).

Read-only. Measures, decides nothing. Writes a report.

    uv run python src/load/v2_ingest/_probe_coverage_statsbomb.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = "data/processed/worldcup.duckdb"
NATION_JSON = Path("data/config/nation_codes.json")
REPORT = Path("data/raw/wc2026/_probe_coverage_statsbomb.txt")

# StatsBomb team spellings that differ from nation_codes.json keys. Best-effort
# seeds; the probe prints any team still unmapped so we can extend this.
SB_TEAM_ALIASES = {
    "Korea Republic": "KOR", "Republic of Korea": "KOR", "South Korea": "KOR",
    "IR Iran": "IRN",
    "Côte d'Ivoire": "CIV", "Cote d'Ivoire": "CIV",
    "Democratic Republic of Congo": "COD", "Congo DR": "COD",
    "Cabo Verde": "CPV",
    "Czechia": "CZE",
    "Türkiye": "TUR", "Turkiye": "TUR",
    "USA": "USA",
}


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
        nation_map = json.loads(NATION_JSON.read_text(encoding="utf-8"))
        nation_map.pop("_comment", None)
        team_to_code = {**nation_map, **SB_TEAM_ALIASES}

        con = duckdb.connect(DB_PATH, read_only=True)
        squad = con.sql(
            "SELECT squad_row_id, name_norm, nation_code, dob FROM wc2026_squad"
        ).df()
        ea = con.sql("SELECT name_norm FROM ea_fc26_player").df()
        players = con.sql(
            "SELECT lower(strip_accents(player_name)) AS name_norm FROM players"
        ).df()
        # distinct StatsBomb persons: one row per (player_id, name_norm, team)
        sb = con.sql(
            "SELECT DISTINCT player_id, "
            "lower(strip_accents(player)) AS name_norm, team "
            "FROM statsbomb_event WHERE player_id IS NOT NULL"
        ).df()
        con.close()

        # --- EA + empirical axes (reproduce S24 baseline as a drift check) ---
        squad["n_ea"] = squad["name_norm"].map(
            ea.groupby("name_norm").size()).fillna(0).astype(int)
        squad["n_pl"] = squad["name_norm"].map(
            players.groupby("name_norm").size()).fillna(0).astype(int)

        # --- StatsBomb axis ---
        sb["nation_code"] = sb["team"].map(team_to_code)
        unmapped = sorted(set(sb.loc[sb["nation_code"].isna(), "team"]))
        sb_name_counts = sb.groupby("name_norm")["player_id"].nunique()
        sb_name_nation = (sb.dropna(subset=["nation_code"])
                          .groupby("name_norm")["nation_code"].apply(set).to_dict())
        squad["n_sb"] = squad["name_norm"].map(sb_name_counts).fillna(0).astype(int)
        squad["sb_strict"] = squad.apply(
            lambda r: r["nation_code"] in sb_name_nation.get(r["name_norm"], set()),
            axis=1)

        n = len(squad)
        has_ea = squad["n_ea"] > 0
        has_pl = squad["n_pl"] > 0
        has_sb_loose = squad["n_sb"] > 0
        has_sb_strict = squad["sb_strict"]

        # --- S24 baseline matrix (cross-check) ---
        both = int((has_ea & has_pl).sum())
        ea_only = int((has_ea & ~has_pl).sum())
        emp_only = int((~has_ea & has_pl).sum())
        prev_dark_mask = ~has_ea & ~has_pl
        prev_dark = int(prev_dark_mask.sum())
        w(f"squad rows: {n}")
        w("\nS24 BASELINE (EA + empirical, exact name_norm) — drift check:")
        w(f"  both={both}  ea_only={ea_only}  emp_only={emp_only}  "
          f"DARK={prev_dark}   (S24 was 536/314/32/365)")

        # --- StatsBomb mapping health ---
        w(f"\nStatsBomb: {sb['player_id'].nunique()} distinct players, "
          f"{sb['team'].nunique()} teams; "
          f"unmapped teams: {len(unmapped)}")
        if unmapped:
            w("  UNMAPPED (add to SB_TEAM_ALIASES, weakens strict match): "
              + ", ".join(repr(t) for t in unmapped))
        sb_nations = set(sb["nation_code"].dropna())
        squad_nations = set(squad["nation_code"])
        w(f"  squad nations present in StatsBomb: "
          f"{len(squad_nations & sb_nations)}/{len(squad_nations)} "
          f"(absent stay dark, e.g. no intl-tournament appearance)")

        # --- StatsBomb match on squad ---
        w(f"\nStatsBomb match on squad (by name_norm): {buckets(squad['n_sb'])}")
        w(f"  -> any SB candidate (loose): {int(has_sb_loose.sum())}/{n} "
          f"({100*has_sb_loose.mean():.1f}%)")
        w(f"  -> name+nation confirmed (strict): {int(has_sb_strict.sum())}/{n} "
          f"({100*has_sb_strict.mean():.1f}%)")

        # --- THE HEADLINE: dark-set shrinkage ---
        rescue_loose = int((prev_dark_mask & has_sb_loose).sum())
        rescue_strict = int((prev_dark_mask & has_sb_strict).sum())
        new_dark_loose = prev_dark - rescue_loose
        new_dark_strict = prev_dark - rescue_strict
        w("\n=== DARK-SET SHRINKAGE (the headline) ===")
        w(f"  previously dark (no EA, no empirical) : {prev_dark}")
        w(f"  ...now lit by StatsBomb (loose name)  : {rescue_loose}  "
          f"-> dark {prev_dark} -> {new_dark_loose}")
        w(f"  ...now lit by StatsBomb (name+nation) : {rescue_strict}  "
          f"-> dark {prev_dark} -> {new_dark_strict}")

        # --- new overall coverage ---
        any_cov_strict = has_ea | has_pl | has_sb_strict
        w(f"\nOVERALL coverage (EA | empirical | SB-strict): "
          f"{int(any_cov_strict.sum())}/{n} ({100*any_cov_strict.mean():.1f}%)")
        w(f"  TRULY DARK now (no source at all): {int((~any_cov_strict).sum())}")

        # --- darkest nations after StatsBomb (strict) ---
        still_dark = squad[~any_cov_strict]
        dark_by_nat = (still_dark.groupby("nation_code").size()
                       .sort_values(ascending=False).head(12))
        w("\ndarkest nations AFTER StatsBomb (top 12):")
        w("  " + ", ".join(f"{nat}:{c}" for nat, c in dark_by_nat.items()))

        # --- who got rescued: sample dark squads now lit by SB ---
        rescued = squad[prev_dark_mask & has_sb_strict]
        rescue_by_nat = (rescued.groupby("nation_code").size()
                         .sort_values(ascending=False).head(12))
        w("\nrescued-by-StatsBomb, by nation (top 12):")
        w("  " + ", ".join(f"{nat}:{c}" for nat, c in rescue_by_nat.items()))

        summary.append(
            f"baseline both={both} ea_only={ea_only} emp_only={emp_only} "
            f"dark={prev_dark}")
        summary.append(
            f"SB loose={int(has_sb_loose.sum())} strict={int(has_sb_strict.sum())} "
            f"| rescued loose={rescue_loose} strict={rescue_strict} "
            f"| dark {prev_dark}->{new_dark_strict}")
        summary.append(
            f"overall covered (strict)={int(any_cov_strict.sum())}/{n} "
            f"truly_dark={int((~any_cov_strict).sum())} unmapped_teams={len(unmapped)}")
    except Exception:
        import traceback
        w("\n!!! ERROR !!!\n" + traceback.format_exc())
        summary.append("ERROR (see report tail)")
        rc = 1

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("coverage-with-StatsBomb probe done. summary:")
    for s in summary:
        print("  " + s)
    print(f"full report -> {REPORT}  ({len(lines)} lines)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
