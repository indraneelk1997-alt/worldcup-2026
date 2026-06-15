"""Build `squad_position_eligibility` (item 9, docs/item9_xi_selection.md §6).

For every wc2026_squad player, pool minutes-by-role across the three empirical
sources, apply the >20% / >=270-min eligibility rule, and fall back to EA
(position + alt_positions) below the floor or with no data.

Sources & linkage (verified S42):
  - Understat + FBref : player_match_all. IDs are SOURCE-NATIVE and split per
                        player: our_player_id is FBref's space, Understat uses
                        its own (verified -- Understat ids overlap our_player_id
                        zero times). So we link via the UNION of our_player_id +
                        all players-table ids sharing the normalised name (the
                        crosswalk), which recovers both. FBref multi-pos tag
                        'POS1,POS2' -> first token.
  - StatsBomb         : modal position per (match,player) from statsbomb_event,
                        minutes from statsbomb_player_match, name-linked to the
                        squad by lower(strip_accents(player)). (~50% squad
                        coverage across all 3; the rest -> EA fallback.)

Writes ONE derived table (CREATE OR REPLACE) -- never touches source tables
(rule 9). Read everything else read-only. Idempotent: rerun rebuilds the table.

Run:  uv run python src/load/v2_ingest/build_position_eligibility.py
"""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CFG = json.loads((ROOT / "data" / "config" / "position_source_map.json").read_text("utf-8"))
DB_PATH = Path(os.environ.get("WC2026_DB", ROOT / "data" / "processed" / "worldcup.duckdb"))

MIN_MINUTES = 270           # eligibility floor (~3 full matches) -> else EA fallback
ELIG_SHARE = 0.20           # >20% of minutes in a role -> eligible
EA_ALT_WEIGHT = 0.6         # synthetic weight of each EA alt vs primary (1.0)


def _map(src: str, raw: str) -> dict | None:
    """Resolve one raw source position -> {code, role, flank, cb_lean?} or None."""
    if raw in CFG["drop"]:
        return None
    if src == "fbref":
        raw = raw.split(",")[0].strip()         # primary token of a combo tag
    return CFG[src].get(raw)


def empirical_minutes(con) -> pd.DataFrame:
    """-> rows of (squad_row_id, role, minutes, source, cb_lean) from all 3 sources."""
    recs: list[dict] = []

    # --- Understat + FBref (club), via the id-union crosswalk ---
    uf = con.execute("""
        WITH xref AS (
            SELECT squad_row_id, our_player_id AS pid FROM wc2026_squad
            UNION
            SELECT s.squad_row_id, p.player_id AS pid
            FROM wc2026_squad s
            JOIN players p ON lower(strip_accents(p.player_name)) = s.name_norm
        )
        SELECT x.squad_row_id, pm.source, pm.position, SUM(pm.minutes) AS minutes
        FROM xref x
        JOIN player_match_all pm ON pm.player_id = x.pid
        WHERE pm.position IS NOT NULL AND pm.minutes IS NOT NULL
        GROUP BY 1, 2, 3
    """).df()
    for r in uf.itertuples(index=False):
        m = _map(r.source, r.position)
        if m:
            recs.append(dict(squad_row_id=r.squad_row_id, role=m["role"],
                             minutes=float(r.minutes), source=r.source,
                             cb_lean=m.get("cb_lean")))

    # --- StatsBomb (international): modal in-match position -> that match's minutes ---
    sb = con.execute("""
        WITH cnt AS (
            SELECT match_id, player_id, position, COUNT(*) AS ev
            FROM statsbomb_event WHERE position IS NOT NULL
            GROUP BY 1, 2, 3),
        modal AS (
            SELECT match_id, player_id, position,
                   ROW_NUMBER() OVER (PARTITION BY match_id, player_id
                                      ORDER BY ev DESC, position) AS rn
            FROM cnt),
        pm AS (
            SELECT m.match_id, m.player_id, m.position AS sb_pos, spm.minutes,
                   lower(strip_accents(trim(spm.player))) AS nkey
            FROM modal m
            JOIN statsbomb_player_match spm
              ON spm.match_id = m.match_id AND spm.player_id = m.player_id
            WHERE m.rn = 1 AND spm.minutes IS NOT NULL)
        SELECT s.squad_row_id, pm.sb_pos AS position, SUM(pm.minutes) AS minutes
        FROM pm JOIN wc2026_squad s
          ON lower(strip_accents(trim(s.player_name))) = pm.nkey
        GROUP BY 1, 2
    """).df()
    for r in sb.itertuples(index=False):
        m = _map("statsbomb", r.position)
        if m:
            recs.append(dict(squad_row_id=r.squad_row_id, role=m["role"],
                             minutes=float(r.minutes), source="statsbomb",
                             cb_lean=m.get("cb_lean")))

    return pd.DataFrame.from_records(
        recs, columns=["squad_row_id", "role", "minutes", "source", "cb_lean"])


def ea_fallback_rows(con, sid: int) -> list[dict]:
    """Synthetic eligibility from EA position + alt_positions for one player."""
    r = con.execute(
        "SELECT e.position, e.alt_positions FROM wc2026_squad s "
        "JOIN ea_fc26_player e ON e.ea_id = s.ea_id WHERE s.squad_row_id = ?",
        [sid]).fetchone()
    if not r or not r[0]:
        return []
    primary, alt_raw = r[0], r[1]
    weights: dict[str, float] = {}
    pm = CFG["ea"].get(primary)
    if pm:
        weights[pm["role"]] = weights.get(pm["role"], 0.0) + 1.0
    if alt_raw:
        try:
            alts = ast.literal_eval(alt_raw)
        except (ValueError, SyntaxError):
            alts = []
        for a in alts:
            am = CFG["ea"].get(a)
            if am:
                weights[am["role"]] = weights.get(am["role"], 0.0) + EA_ALT_WEIGHT
    if not weights:
        return []
    tot = sum(weights.values())
    modal = max(weights, key=weights.get)
    return [dict(squad_row_id=sid, role=role, minutes=None,
                 minutes_share=w / tot, is_modal=(role == modal),
                 eligible=True,                       # EA lists it -> eligible
                 source_mix="ea", cb_lean=None, basis="ea_fallback")
            for role, w in weights.items()]


# coarse last-resort: when a player has neither >=270 empirical min NOR a
# mapped EA position, fall back to the squad's coarse group so he stays
# placeable (same behaviour as the old group-only autopick -- no regression).
ROLE_BY_GROUP = {
    "GK":  (["GK"], "GK"),
    "DEF": (["CB", "RB", "LB"], "CB"),
    "MID": (["DM", "CM", "CAM"], "CM"),
    "FWD": (["WIDE_L", "WIDE_R", "ST"], "ST"),
}


def group_fallback_rows(con, sid: int) -> list[dict]:
    r = con.execute("SELECT primary_position_group FROM wc2026_squad "
                    "WHERE squad_row_id = ?", [sid]).fetchone()
    grp = r[0] if r else None
    if grp not in ROLE_BY_GROUP:
        return []
    roles, modal = ROLE_BY_GROUP[grp]
    share = 1.0 / len(roles)
    return [dict(squad_row_id=sid, role=role, minutes=None, minutes_share=share,
                 is_modal=(role == modal), eligible=True, source_mix="group",
                 cb_lean=None, basis="group_fallback") for role in roles]


def build() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH))            # writable: builds its own table
    emp = empirical_minutes(con)

    out_rows: list[dict] = []
    all_sids = [r[0] for r in con.execute(
        "SELECT squad_row_id FROM wc2026_squad").fetchall()]

    # per-player CB lean (majority of StatsBomb CB-side votes), and role totals
    by_player = {sid: g for sid, g in emp.groupby("squad_row_id")} if len(emp) else {}

    for sid in all_sids:
        g = by_player.get(sid)
        total = float(g["minutes"].sum()) if g is not None else 0.0
        if g is None or total < MIN_MINUTES:
            out_rows.extend(ea_fallback_rows(con, sid) or group_fallback_rows(con, sid))
            continue
        roles = g.groupby("role")["minutes"].sum()
        modal_role = roles.idxmax()
        leans = g.loc[g["cb_lean"].notna(), "cb_lean"]
        cb_lean = leans.mode().iat[0] if len(leans) else None
        srcs = ",".join(sorted(g["source"].unique()))
        for role, mins in roles.items():
            share = mins / total
            out_rows.append(dict(
                squad_row_id=sid, role=role, minutes=int(round(mins)),
                minutes_share=share, is_modal=(role == modal_role),
                eligible=(share > ELIG_SHARE), source_mix=srcs,
                cb_lean=(cb_lean if role == "CB" else None), basis="empirical"))

    df = pd.DataFrame.from_records(out_rows, columns=[
        "squad_row_id", "role", "minutes", "minutes_share", "is_modal",
        "eligible", "source_mix", "cb_lean", "basis"])

    con.execute("CREATE OR REPLACE TABLE squad_position_eligibility AS "
                "SELECT * FROM df")
    con.close()
    return df


def _report(df: pd.DataFrame):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    n_players = df["squad_row_id"].nunique()
    by_basis = df.groupby("basis")["squad_row_id"].nunique()
    print(f"squad_position_eligibility: {len(df)} rows, {n_players} players")
    print(f"  basis: {by_basis.to_dict()}")
    print(f"  eligible rows: {int(df['eligible'].sum())}; "
          f"cb_lean set: {int(df['cb_lean'].notna().sum())}\n")
    for name in ("Harry Kane", "Marcus Rashford", "Marc Cucurella",
                 "Jude Bellingham", "Bukayo Saka"):
        q = con.execute("""
            SELECT e.role, e.minutes, round(e.minutes_share,3) AS share,
                   e.is_modal, e.eligible, e.source_mix, e.cb_lean, e.basis
            FROM squad_position_eligibility e
            JOIN wc2026_squad s ON s.squad_row_id = e.squad_row_id
            WHERE s.player_name = ? ORDER BY share DESC""", [name]).df()
        print(f"-- {name} --")
        print(q.to_string(index=False) if len(q) else "   (not in squad)")
        print()
    con.close()


if __name__ == "__main__":
    _report(build())
