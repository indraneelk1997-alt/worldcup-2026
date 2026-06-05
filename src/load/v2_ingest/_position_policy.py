"""
_position_policy.py  —  V1.04 shared position policy (S18).

INGEST ARCHITECTURE: v2 (append-only, source-centric)

Extracted, byte-for-byte, from V1.03's
`src/load/backfill_player_match.py` (`compute_effective_position`,
`CLASS_TO_POSITION`). V1.03 contains two duplicate copies of this
policy — `backfill_player_match.py` and `load_md38_actuals.py` — whose
docstrings flag the drift risk. V1.04 imports from this module
instead. V1.03 files are intentionally NOT updated; the V1.04 ingest
architecture rule is "V1 loaders only migrate when they break"
(see `docs/v104_ingest_design.md` migration rules, and S18 design
notes in `docs/v104_ingest_understat.md`).

POLICY-C: EFFECTIVE POSITION FOR SUB ROWS

`player_match_stats.effective_position` is `position` for non-Sub
rows (trivial passthrough). For `'Sub'` rows, the value is derived
via a 3-step fallback chain:
  1. Player's most-common non-Sub position across all per-match rows
     **in this dataset** (counted by row count). The "dataset" is
     whatever DataFrame is passed in — for V1.04, one
     `(league, season)` worth of player-match data.
  2. If the player has only Sub rows in this dataset: map from their
     `player_season_stats.position_class` via `CLASS_TO_POSITION`
     (DEF -> 'DC', MID -> 'MC', FWD -> 'FW', GK -> 'GK').
  3. Else: keep `effective_position = 'Sub'`.

NEW-LEAGUE BEHAVIOUR (S18 decision (a))

For a fresh non-PL ingest, `player_season_stats` has zero rows for
that league's players, so step 2 is effectively a no-op for
sub-only players and they land on step 3 ('Sub'). 'Sub' is a valid
schema value (`player_match_schema.py` allows it). The alternative
(derive `player_season_stats` for the new league first, so step 2
can fire) was rejected to keep derived-state computation out of the
ingest path. See `docs/v104_ingest_understat.md`, "New-league fallback".
"""
from __future__ import annotations

from collections import Counter


# Fallback step 2: position class -> default per-match position code.
# Same map as V1.03 (`backfill_player_match.py` line 57,
# `load_md38_actuals.py` line 65). Keep them aligned if either changes.
CLASS_TO_POSITION = {
    "GK":  "GK",
    "DEF": "DC",
    "MID": "MC",
    "FWD": "FW",
}


def compute_effective_position(df, season_stats_class_lookup):
    """Return `{(game_id, player_id) -> effective_position_str}`.

    Applies the policy-C 3-step fallback documented in the module
    docstring. Logic is identical to V1.03's `compute_effective_position`
    in `backfill_player_match.py`; behaviour MUST NOT drift.

    Parameters
    ----------
    df : pandas.DataFrame
        Per-player-match rows with at least the columns
        `game_id`, `player_id`, `position`. Index irrelevant
        (caller has already reset_index if Understat-shaped).
    season_stats_class_lookup : dict[int, str]
        Map from `player_id` to that player's `position_class`
        (e.g. `'FWD'`) from `player_season_stats`. Pass an empty
        dict for new-league loads where no rows exist yet — step 2
        will simply never fire and sub-only players will land on
        step 3 ('Sub').

    Returns
    -------
    dict[(int, int), str]
        Keyed by (game_id, player_id). Value is the resolved
        `effective_position` string. Same as `position` for non-Sub
        rows; resolved per the fallback chain for Sub rows.

    Side effects
    ------------
    Prints a small breakdown of the sub-only counts to stdout, so
    operators can eyeball how many players hit each fallback step.
    """
    # Build a player_id -> Counter of non-Sub positions across all rows.
    non_sub = df[df["position"] != "Sub"]
    player_pos_counter = {}
    for pid, pos in zip(non_sub["player_id"], non_sub["position"]):
        player_pos_counter.setdefault(int(pid), Counter())[pos] += 1

    # Compute primary (most common) non-Sub position per player.
    player_primary = {}
    for pid, ctr in player_pos_counter.items():
        player_primary[pid] = ctr.most_common(1)[0][0]

    # Walk the full df and assign effective_position.
    eff_lookup = {}
    sub_only_count = 0
    fallback_to_class_count = 0
    fallback_to_sub_count = 0
    for game_id, pid, pos in zip(
        df["game_id"], df["player_id"], df["position"]
    ):
        key = (int(game_id), int(pid))
        if pos != "Sub":
            eff_lookup[key] = pos
            continue
        # Step 2: try player's own primary non-Sub position
        primary = player_primary.get(int(pid))
        if primary is not None:
            eff_lookup[key] = primary
            continue
        sub_only_count += 1
        # Step 3: try season_stats class mapping
        # season_stats_class_lookup keyed by player_id alone (player's
        # primary class is stable per player season).
        season_class = season_stats_class_lookup.get(int(pid))
        if season_class is not None:
            mapped = CLASS_TO_POSITION.get(season_class)
            if mapped is not None:
                eff_lookup[key] = mapped
                fallback_to_class_count += 1
                continue
        # Step 4: keep as Sub
        eff_lookup[key] = "Sub"
        fallback_to_sub_count += 1

    print(f"  Sub-only players (no non-Sub rows in this dataset): "
          f"{sub_only_count} rows affected")
    print(f"    of which backfilled from season_stats class: "
          f"{fallback_to_class_count}")
    print(f"    of which kept as 'Sub' (no class either): "
          f"{fallback_to_sub_count}")
    return eff_lookup
