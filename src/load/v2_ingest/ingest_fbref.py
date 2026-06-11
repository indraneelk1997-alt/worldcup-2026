"""
ingest_fbref.py — V1.04 FBref loader (Option C, source-separated tables).

Built section-by-section (S22):
  * Section A (done):  read_schedule -> games  (shared dim)
  * Section B (done):  read_team_match_stats -> team_match_fbref
  * Section C (done):  read_player_match_stats -> players + player_match_fbref

Design references: docs/v104_ingest_competitions.md ("Schema deltas —
RESOLVED S22"), docs/v104_schema_migration.md. Schema already migrated
(migrate_v104_fbref_schema.py). Dry-run default; --apply writes.

Section A responsibilities (decisions a/b/c):
  * mint surrogate INTEGER game_id (base 10_000_000), keyed on the FBref
    hash stored in games.source_game_id — idempotent: reuse existing id
    for an already-loaded hash, never re-mint.
  * map season '2425' -> '2024-2025' (FBref index form, same as Understat).
  * parse the score string into home/away goals + shootout pens.
  * write source='fbref', stage (round), venue (stadium).

    uv run python src/load/v2_ingest/ingest_fbref.py --season 2024-2025          # dry-run
    uv run python src/load/v2_ingest/ingest_fbref.py --season 2024-2025 --apply
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import warnings
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd
from dateutil.relativedelta import relativedelta
from soccerdata import FBref

# soccerdata's lxml tree.find('//...') raises a noisy FutureWarning once
# per table (hundreds of lines on a full read). It's a soccerdata-internal
# call we can't change; silence it so loader output stays readable.
warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, str(Path(__file__).parent))
from _position_policy import fbref_effective_position  # noqa: E402

DB_PATH = "data/processed/worldcup.duckdb"
DEFAULT_LEAGUE = "UEFA-Champions League"
GAME_ID_BASE = 10_000_000

# FBref's season MultiIndex value is the short form, same as Understat.
SEASON_SD_TO_DB = {"2425": "2024-2025", "2526": "2025-2026"}

# Score parser (observed S22): '9–2' (en-dash U+2013), and shootouts wrap
# BOTH sides: '(1) 0–1 (4)' = reg 0–1, pens home 1 / away 4. Optional
# leading/trailing paren groups; dash family split.
SCORE_RE = re.compile(
    r"^\s*(?:\((\d+)\)\s*)?(\d+)\s*[–—-]\s*(\d+)(?:\s*\((\d+)\))?\s*$"
)

# Knockout/league-phase labels observed for UCL — used as a secondary
# cross-check in Section B (decision g). Not enforced here.
KNOWN_UCL_ROUNDS = {
    "League phase", "Knockout phase play-offs", "Round of 16",
    "Quarter-finals", "Semi-finals", "Final",
}

_EMPTY_SCORE = {"", "<na>", "nan", "none"}


def parse_score(raw) -> tuple:
    """Return (home_goals, away_goals, home_pens, away_pens).

    Unplayed / missing -> all None. Penalties None when no shootout.
    Raises ValueError on a non-empty string that doesn't match — we want
    to fail loud on FBref format drift, not silently drop a result.
    """
    if raw is None:
        return (None, None, None, None)
    s = str(raw).strip()
    if s.lower() in _EMPTY_SCORE:
        return (None, None, None, None)
    m = SCORE_RE.match(s)
    if not m:
        raise ValueError(f"unparseable score string: {raw!r}")
    home_pens, home_goals, away_goals, away_pens = m.groups()
    return (
        int(home_goals),
        int(away_goals),
        int(home_pens) if home_pens is not None else None,
        int(away_pens) if away_pens is not None else None,
    )


def map_season(sd_value: str) -> str:
    db = SEASON_SD_TO_DB.get(str(sd_value))
    if db is None:
        raise ValueError(
            f"no season map for FBref season {sd_value!r} "
            f"(extend SEASON_SD_TO_DB)"
        )
    return db


def _selftest_parser() -> None:
    """Observed cases must parse exactly (S14: verify against real data)."""
    assert parse_score("9–2") == (9, 2, None, None)
    assert parse_score("(1) 0–1 (4)") == (0, 1, 1, 4)
    assert parse_score("(2) 1–0 (4)") == (1, 0, 2, 4)
    assert parse_score("0–0") == (0, 0, None, None)
    assert parse_score("") == (None, None, None, None)
    assert parse_score(None) == (None, None, None, None)


GAMES_INSERT = """
INSERT OR IGNORE INTO games
    (game_id, season, match_date, home_team, away_team, league,
     source, source_game_id, stage, venue,
     home_goals, away_goals, home_pens, away_pens)
VALUES (?, ?, ?, ?, ?, ?, 'fbref', ?, ?, ?, ?, ?, ?, ?)
"""


def load_games(con, scraper, league: str, apply: bool) -> dict:
    """Section A. Returns {source_game_id(hash): game_id} for B/C."""
    print("\n-- Section A: read_schedule -> games --")
    sched = scraper.read_schedule().reset_index()
    print(f"  schedule rows: {len(sched)}")

    # existing FBref games (idempotency): hash -> surrogate id
    existing = {
        h: g for h, g in con.execute(
            "SELECT source_game_id, game_id FROM games WHERE source = 'fbref'"
        ).fetchall()
    }
    cur_max = max(existing.values()) if existing else GAME_ID_BASE - 1
    print(f"  existing FBref games: {len(existing)} "
          f"(max id {cur_max if existing else '-'})")

    rows, parse_fail, shootouts, n_new = [], [], 0, 0
    for r in sched.itertuples(index=False):
        hashid = str(r.game_id)
        season = map_season(r.season)
        match_date = pd.to_datetime(r.date).date()
        try:
            hg, ag, hp, ap = parse_score(r.score)
        except ValueError as e:
            parse_fail.append((hashid, r.score, str(e)))
            continue
        if hp is not None or ap is not None:
            shootouts += 1
        if hashid in existing:
            gid = existing[hashid]
        else:
            cur_max += 1
            gid = cur_max
            n_new += 1
        stage = None if pd.isna(r.round) else str(r.round)
        venue = None if pd.isna(r.venue) else str(r.venue)
        rows.append((gid, season, match_date, str(r.home_team),
                     str(r.away_team), league, hashid, stage, venue,
                     hg, ag, hp, ap))

    # fail loud on any unparseable score
    if parse_fail:
        print(f"  !! {len(parse_fail)} unparseable score(s):")
        for h, sc, err in parse_fail[:10]:
            print(f"     {h}: {sc!r} — {err}")
        raise SystemExit("aborting: score parser needs fixing (see above)")

    print(f"  parsed OK: {len(rows)}  | new ids: {n_new}  | "
          f"existing: {len(rows) - n_new}  | shootouts: {shootouts}")
    print(f"  stages: {sorted({x[7] for x in rows if x[7]})}")
    print("  sample (gid, season, date, home, away, hg-ag, pens):")
    for x in rows[:5]:
        pens = f" pens {x[11]}-{x[12]}" if x[11] is not None else ""
        print(f"    {x[0]} {x[1]} {x[2]} {x[3]} v {x[4]}  "
              f"{x[9]}-{x[10]}{pens}")

    hash_to_gid = {x[6]: x[0] for x in rows}   # hash -> surrogate game_id
    hash_to_date = {x[6]: x[2] for x in rows}  # hash -> match_date (for dob calc)
    if apply:
        con.executemany(GAMES_INSERT, rows)
        print(f"  APPLIED: INSERT OR IGNORE {len(rows)} games rows")
    else:
        print(f"  DRY-RUN: would INSERT OR IGNORE {len(rows)} games rows")
    return hash_to_gid, hash_to_date


# ---------------------------------------------------------- Section B
# team_match comes back all-comps contaminated with league=<NA>
# (decision g). game_id is NOT a column — parse the 8-char hash from the
# match_report URL, then keep only rows whose hash is in the clean
# read_schedule set (primary filter). round-enum is the secondary
# tripwire.
MATCH_REPORT_RE = re.compile(r"/matches/([0-9a-z]{8})/")

# source columns we require present (fail loud if FBref dropped one)
EXPECTED_TM_COLS = [
    "venue", "result", "GF", "GA", "opponent", "Poss", "Attendance",
    "Captain", "Formation", "Opp Formation", "Referee", "round",
    "match_report",
]
# rename the spaced/odd source names to clean identifiers so itertuples works
TM_RENAME = {
    "venue": "side_raw",          # 'Home'/'Away' (NOT the stadium)
    "GF": "goals", "GA": "opponent_goals", "Poss": "possession",
    "Attendance": "attendance", "Captain": "captain",
    "Formation": "formation", "Opp Formation": "opp_formation",
    "Referee": "referee",
}

TEAM_MATCH_INSERT = """
INSERT OR IGNORE INTO team_match_fbref
    (game_id, team, side, season, opponent, league, goals, opponent_goals,
     result, possession, attendance, captain, formation, opp_formation, referee)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _to_int(v):
    return None if pd.isna(v) else int(v)


def _to_float(v):
    return None if pd.isna(v) else float(v)


def _to_str(v):
    return None if pd.isna(v) else str(v)


# team_match GF/GA also carry shootout pens in parens, e.g. '1 (2)'.
# We keep regulation goals (leading int); pens already live on games.
_GOALS_RE = re.compile(r"^\s*(\d+)")


def _goals_int(v):
    if pd.isna(v):
        return None
    m = _GOALS_RE.match(str(v).strip())
    if not m:
        raise ValueError(f"unparseable goals value: {v!r}")
    return int(m.group(1))


def _extract_hash(url):
    if pd.isna(url):
        return None
    m = MATCH_REPORT_RE.search(str(url))
    return m.group(1) if m else None


def load_team_match(con, scraper, league: str, hash_to_gid: dict,
                    apply: bool) -> None:
    """Section B. Filter all-comps team_match to this comp, assign league."""
    print("\n-- Section B: read_team_match_stats -> team_match_fbref --")
    tm = scraper.read_team_match_stats(stat_type="schedule").reset_index()
    print(f"  all-comps rows (contaminated): {len(tm)}")

    missing = [c for c in EXPECTED_TM_COLS if c not in tm.columns]
    if missing:
        raise SystemExit(f"team_match missing expected columns: {missing}")

    tm["hashid"] = tm["match_report"].map(_extract_hash)

    # primary filter: hash membership in the clean read_schedule set
    kept = tm[tm["hashid"].isin(hash_to_gid)].copy()
    print(f"  kept after game_id-membership filter: {len(kept)} "
          f"(dropped {len(tm) - len(kept)} other-comp rows)")

    # secondary tripwire (decision g): kept rows' round must be a known
    # UCL round; disagreement signals FBref drift -> fail loud
    bad = kept[~kept["round"].astype(str).isin(KNOWN_UCL_ROUNDS)]
    if len(bad):
        print("  !! kept rows with non-UCL round (primary/secondary disagree):")
        print(bad[["hashid", "round", "match_report"]].head(10).to_string())
        raise SystemExit("aborting: filter disagreement (decision g)")

    # invariant: rows == 2 * distinct games
    n_games = kept["hashid"].nunique()
    ok = "OK" if len(kept) == 2 * n_games else "MISMATCH"
    print(f"  distinct games: {n_games} | rows: {len(kept)} | "
          f"2x games = {2 * n_games}  {ok}")
    print(f"  distinct teams: {kept['team'].nunique()}")

    kept = kept.rename(columns=TM_RENAME)
    rows = []
    for r in kept.itertuples(index=False):
        rows.append((
            hash_to_gid[r.hashid], _to_str(r.team),
            str(r.side_raw).strip().lower(),  # 'home'/'away'
            map_season(r.season), _to_str(r.opponent), league,
            _goals_int(r.goals), _goals_int(r.opponent_goals), _to_str(r.result),
            _to_float(r.possession), _to_int(r.attendance), _to_str(r.captain),
            _to_str(r.formation), _to_str(r.opp_formation), _to_str(r.referee),
        ))

    print("  sample (gid, team, side, goals-oppgoals, formation):")
    for x in rows[:5]:
        print(f"    {x[0]} {x[1]:<22} {x[2]:<5} {x[6]}-{x[7]}  {x[12]}")

    if apply:
        con.executemany(TEAM_MATCH_INSERT, rows)
        print(f"  APPLIED: INSERT OR IGNORE {len(rows)} team_match_fbref rows")
    else:
        print(f"  DRY-RUN: would INSERT OR IGNORE {len(rows)} rows")


# ---------------------------------------------------------- Section C
# read_player_match_stats: MultiIndex columns (decision f), no numeric
# player_id (mint surrogates on (name, nation, dob), decision: rough
# match), age 'YY-DDD' -> dob (decision e), pos via source-aware policy
# (decision d). position_id is Understat-only -> left NULL for FBref.
FBREF_PLAYER_BASE = 50_000_000

# flattened FBref column -> our schema column (anti-corruption layer,
# decision f). EVERY flattened source column must be a key here or we
# fail loud (FBref drift alarm). Identity cols map to themselves.
FBREF_PLAYER_COLMAP = {
    "jersey_number": "jersey_number", "nation": "nation", "pos": "pos",
    "age": "age", "min": "minutes", "game_id": "game_id",
    "performance_gls": "goals", "performance_ast": "assists",
    "performance_pk": "pens_made", "performance_pkatt": "pens_att",
    "performance_sh": "shots", "performance_sot": "shots_on_target",
    "performance_crdy": "yellow_cards", "performance_crdr": "red_cards",
    "performance_fls": "fouls", "performance_fld": "fouled",
    "performance_off": "offsides", "performance_crs": "crosses",
    "performance_tklw": "tackles_won", "performance_int": "interceptions",
    "performance_og": "own_goals", "performance_pkwon": "pens_won",
    "performance_pkcon": "pens_conceded",
}

PLAYER_MATCH_INSERT = """
INSERT OR IGNORE INTO player_match_fbref
    (game_id, player_id, season, team, league, position, effective_position,
     jersey_number, nation, minutes, goals, assists, pens_made, pens_att,
     shots, shots_on_target, yellow_cards, red_cards, fouls, fouled, offsides,
     crosses, tackles_won, interceptions, own_goals, pens_won, pens_conceded)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_AGE_RE = re.compile(r"^\s*(\d+)-(\d+)\s*$")


def _flatten_fbref_columns(cols) -> list:
    """('Performance','Gls')->'performance_gls'; ('pos','')->'pos'.
    Drop blank/Unnamed top levels to the leaf, lowercase (decision f)."""
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(p) for p in c
                     if p is not None and str(p) != ""
                     and not str(p).startswith("Unnamed")]
            flat = "_".join(parts) if parts else str(c[-1])
        else:
            flat = str(c)
        out.append(flat.lower().strip())
    return out


def _norm_name(name):
    """Accent-stripped, lowercased, punctuation-collapsed name — the
    crosswalk-ready key component (Indraneel's rough-match note)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _dob_from_age(age, match_date):
    """'30-246' + match_date -> exact DOB via relativedelta (decision e)."""
    if age is None or match_date is None or pd.isna(age):
        return None
    m = _AGE_RE.match(str(age))
    if not m:
        return None
    return match_date - relativedelta(years=int(m.group(1)), days=int(m.group(2)))


def _rough_name_match(a, b) -> bool:
    """Tolerate abbreviations: same surname + same first-initial counts
    as a match (e.g. 'a davies' ~ 'alphonso davies'). Used only within
    a shared (nation, dob) anchor, so collision risk is low."""
    if a == b:
        return True
    if not a or not b:
        return False
    ta, tb = a.split(), b.split()
    return bool(ta and tb and ta[-1] == tb[-1] and ta[0][:1] == tb[0][:1])


def resolve_player_ids(con, parsed: list) -> tuple:
    """Mint/reuse surrogate player_ids keyed on (norm_name, nation).

    dob is NOT part of the key: a player's derived dob drifts by a day
    or two across his matches (FBref age-rounding), which would split
    one player into several ids. Instead we compute a canonical dob =
    the modal derived dob per (name, nation), store that, and anchor the
    rough abbreviation-matcher on (nation, canonical_dob).

    Idempotent: existing FBref players (id >= base) are reconstructed
    from players + player_match_fbref and reused.

    Returns (key_to_pid, canonical_dob_by_key, stats).
    """
    base = FBREF_PLAYER_BASE

    # canonical dob per (norm_name, nation) = modal non-None derived dob
    dob_votes = {}
    keys = set()
    for p in parsed:
        k = (p["norm_name"], p["nation"])
        keys.add(k)
        if p["dob"] is not None:
            dob_votes.setdefault(k, Counter())[p["dob"]] += 1
    canonical = {k: (dob_votes[k].most_common(1)[0][0] if k in dob_votes else None)
                 for k in keys}

    # existing FBref players, reconstructed key (norm_name, nation)
    existing = con.execute(
        "SELECT p.player_id, p.player_name, p.player_dob, ANY_VALUE(pmf.nation) "
        "FROM players p JOIN player_match_fbref pmf ON p.player_id = pmf.player_id "
        "WHERE p.player_id >= ? "
        "GROUP BY p.player_id, p.player_name, p.player_dob",
        [base],
    ).fetchall()
    exact, by_anchor, cur_max = {}, {}, base - 1
    for pid, pname, pdob, pnat in existing:
        k = (_norm_name(pname), pnat)
        dob_iso = pdob.isoformat() if pdob else None
        exact[k] = pid
        by_anchor.setdefault((pnat, dob_iso), []).append((k[0], pid))
        cur_max = max(cur_max, pid)

    stats = {"distinct": len(keys), "reused": 0, "minted": 0, "rough": 0}
    key_to_pid = {}
    for k in sorted(keys):
        nn, nat = k
        if k in exact:
            key_to_pid[k] = exact[k]
            stats["reused"] += 1
            continue
        dob_iso = canonical[k].isoformat() if canonical[k] else None
        pid = None
        if nat is not None and dob_iso is not None:
            for ename, epid in by_anchor.get((nat, dob_iso), []):
                if _rough_name_match(nn, ename):
                    pid = epid
                    stats["rough"] += 1
                    break
        if pid is None:
            cur_max += 1
            pid = cur_max
            stats["minted"] += 1
        exact[k] = pid
        by_anchor.setdefault((nat, dob_iso), []).append((nn, pid))
        key_to_pid[k] = pid
    return key_to_pid, canonical, stats


def load_player_match(con, scraper, league: str, hash_to_gid: dict,
                      hash_to_date: dict, apply: bool) -> None:
    """Section C. players (surrogate ids + dob) + player_match_fbref."""
    print("\n-- Section C: read_player_match_stats -> players + player_match_fbref --")
    pm = scraper.read_player_match_stats(stat_type="summary")

    flat = _flatten_fbref_columns(pm.columns)
    unmapped = [c for c in flat if c not in FBREF_PLAYER_COLMAP]
    if unmapped:
        raise SystemExit(f"unmapped FBref columns (decision f, fail loud): {unmapped}")
    pm = pm.copy()
    pm.columns = [FBREF_PLAYER_COLMAP[c] for c in flat]
    pm = pm.reset_index()  # adds league, season, game, team, player
    print(f"  player-match rows: {len(pm)}")

    pos_codes = {r[0] for r in con.execute(
        "SELECT position_code FROM positions").fetchall()}

    parsed, bad_pos = [], set()
    for r in pm.itertuples(index=False):
        gid = hash_to_gid.get(str(r.game_id))
        if gid is None:
            continue  # player_match is comp-clean; should not happen
        eff = fbref_effective_position(_to_str(r.pos))
        if eff is not None and eff not in pos_codes:
            bad_pos.add((_to_str(r.pos), eff))
        name = _to_str(r.player)
        parsed.append({
            "gid": gid, "season": map_season(r.season), "team": _to_str(r.team),
            "name": name, "norm_name": _norm_name(name), "nation": _to_str(r.nation),
            "dob": _dob_from_age(r.age, hash_to_date.get(str(r.game_id))),
            "raw_pos": _to_str(r.pos), "eff": eff,
            "jersey": _to_int(r.jersey_number), "minutes": _to_int(r.minutes),
            "goals": _to_int(r.goals), "assists": _to_int(r.assists),
            "pens_made": _to_int(r.pens_made), "pens_att": _to_int(r.pens_att),
            "shots": _to_int(r.shots), "sot": _to_int(r.shots_on_target),
            "crdy": _to_int(r.yellow_cards), "crdr": _to_int(r.red_cards),
            "fls": _to_int(r.fouls), "fld": _to_int(r.fouled),
            "off": _to_int(r.offsides), "crs": _to_int(r.crosses),
            "tklw": _to_int(r.tackles_won), "intc": _to_int(r.interceptions),
            "og": _to_int(r.own_goals), "pkwon": _to_int(r.pens_won),
            "pkcon": _to_int(r.pens_conceded),
        })

    if bad_pos:
        print("  !! effective positions not in positions table:")
        for rp, e in sorted(bad_pos):
            print(f"     raw {rp!r} -> {e!r}")
        raise SystemExit("aborting: unhandled position code (extend policy/migration)")

    key_to_pid, canonical_dob, mstats = resolve_player_ids(con, parsed)
    print(f"  player keys (name,nation): {mstats['distinct']} | "
          f"reused: {mstats['reused']} | minted: {mstats['minted']} | "
          f"rough-merges: {mstats['rough']}")

    def pkey(p):
        return (p["norm_name"], p["nation"])

    players_rows, pm_rows = {}, []
    for p in parsed:
        k = pkey(p)
        pid = key_to_pid[k]
        players_rows.setdefault(pid, (pid, p["name"], canonical_dob[k]))
        pm_rows.append((
            p["gid"], pid, p["season"], p["team"], league,
            p["raw_pos"], p["eff"], p["jersey"], p["nation"],
            p["minutes"], p["goals"], p["assists"], p["pens_made"], p["pens_att"],
            p["shots"], p["sot"], p["crdy"], p["crdr"], p["fls"], p["fld"],
            p["off"], p["crs"], p["tklw"], p["intc"], p["og"], p["pkwon"], p["pkcon"],
        ))

    n_pl_dob = sum(1 for v in players_rows.values() if v[2] is not None)
    print(f"  players to upsert: {len(players_rows)} (with dob: {n_pl_dob})")
    print("  sample (pid, name, dob, team, pos->eff, min, G-A):")
    for row in pm_rows[:5]:
        pid = row[1]
        print(f"    {pid} {players_rows[pid][1]:<20} {players_rows[pid][2]} "
              f"{row[3]:<14} {row[5]}->{row[6]}  min{row[9]} {row[10]}-{row[11]}")

    if apply:
        con.executemany(
            "INSERT OR IGNORE INTO players (player_id, player_name, player_dob) "
            "VALUES (?, ?, ?)", list(players_rows.values()))
        con.executemany(PLAYER_MATCH_INSERT, pm_rows)
        print(f"  APPLIED: {len(players_rows)} players, {len(pm_rows)} player_match_fbref rows")
    else:
        print(f"  DRY-RUN: would upsert {len(players_rows)} players, "
              f"{len(pm_rows)} player_match_fbref rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default=DEFAULT_LEAGUE)
    ap.add_argument("--season", required=True, help="DB form e.g. 2024-2025")
    ap.add_argument("--apply", action="store_true",
                    help="execute writes (default: dry-run, read-only)")
    args = ap.parse_args()

    _selftest_parser()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 70)
    print(f"  ingest_fbref Section A — {mode}")
    print(f"  league={args.league}  season={args.season}")
    print("=" * 70)

    if args.league not in FBref.available_leagues():
        print(f"FAIL — '{args.league}' not in FBref.available_leagues(); "
              f"run setup_soccerdata_overlay.py")
        return 2

    # FBref season form is the short '2425'; pass DB form's short version
    sd_season = {v: k for k, v in SEASON_SD_TO_DB.items()}.get(args.season)
    if sd_season is None:
        print(f"FAIL — no FBref season code for {args.season!r}")
        return 2

    scraper = FBref(leagues=[args.league], seasons=args.season)
    con = duckdb.connect(DB_PATH, read_only=not args.apply)
    try:
        hash_to_gid, hash_to_date = load_games(con, scraper, args.league,
                                               args.apply)
        load_team_match(con, scraper, args.league, hash_to_gid, args.apply)
        load_player_match(con, scraper, args.league, hash_to_gid,
                          hash_to_date, args.apply)
    finally:
        con.close()
    print("\n" + "=" * 70)
    print("  Sections A+B+C complete.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
