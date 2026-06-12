"""
_probe_goal_traceback.py  (S32, DELETABLE — exploratory)

Walk the RAW event stream (last K events by event_index, CROSSING possession
turnovers) before each open-play goal, to surface the "chaos value" of zones that
clean-possession Markov xT cannot see: a ball WON or lost-then-won in an advanced
wide/half-space zone, converted seconds later.

Surfaces:
  - raw last-3/5/10 zone frequency (includes the turnover, the recovery, duels)
  - REGAIN/spark zone: where the goal's possession was won (turnover -> goal)
  - annotated example chains showing the possession flip inline
Compared to zone_xt. Read-only. This motivates a transition/turnover-aware xT.

    uv run python src/load/v2_ingest/_probe_goal_traceback.py
"""
from __future__ import annotations
import duckdb, numpy as np
from derive_zone_xt import load_grid, zone_of, DB

g, band_cuts, lane_cuts, n_bands, n_lanes = load_grid()
Z = n_bands * n_lanes
BN, LN = g["bands"]["names"], g["lanes"]["names"]


def zlabel(z):
    return f"B{z // n_lanes + 1}-{LN[z % n_lanes]}"


def grid_print(title, vec, as_pct=False):
    m = vec.reshape(n_bands, n_lanes)
    print(f"\n{title}  (rows B6 opp-box -> B1; cols {' '.join(LN)})")
    for b in range(n_bands - 1, -1, -1):
        cells = "  ".join((f"{m[b,l]*100:5.1f}" if as_pct else f"{m[b,l]:.4f}") for l in range(n_lanes))
        print(f"  {BN[b]:11} {cells}")


def main():
    con = duckdb.connect(str(DB), read_only=True)
    ev = con.execute("""
        SELECT match_id, event_index, possession, possession_team, type, outcome, x, y,
               json_extract_string(raw, '$.shot.type.name') AS shot_type
        FROM statsbomb_event
        WHERE x IS NOT NULL AND y IS NOT NULL
        ORDER BY match_id, event_index
    """).df()
    xt = con.execute("SELECT zone_id, xt FROM zone_xt ORDER BY zone_id").df()["xt"].values
    con.close()

    ev["zone"] = zone_of(ev.x, ev.y, band_cuts, lane_cuts, n_lanes)
    by_match = {mid: gdf.reset_index(drop=True) for mid, gdf in ev.groupby("match_id")}

    goals_all = ev[(ev.type == "Shot") & (ev.outcome == "Goal")]
    goals = goals_all[goals_all.shot_type == "Open Play"]
    print(f"goals: {len(goals_all)} total, {len(goals)} open-play (used)")

    raw_freq = {3: np.zeros(Z), 5: np.zeros(Z), 10: np.zeros(Z)}
    regain = np.zeros(Z)          # zone where the goal's possession was WON (turnover spark)
    n_used = n_turnover_spark = 0
    chains = []

    for _, gl in goals.iterrows():
        gm = by_match[gl.match_id]
        pos = gm.index[gm.event_index == gl.event_index]
        if len(pos) == 0:
            continue
        i = int(pos[0])
        win = gm.iloc[max(0, i - 10):i]          # last <=10 RAW events, crosses turnovers
        if len(win) == 0:
            continue
        n_used += 1
        # CRITICAL: StatsBomb normalises each team to attack +x. Crossing a turnover
        # mixes frames, so rotate the OPPONENT's events into the scorer's frame
        # (180-deg point reflection) before zoning — else conceding-team events near
        # the goal mirror to B1 (the S31 lesson).
        scorer = gl.possession_team
        opp = win.possession_team.values != scorer
        wx = np.where(opp, 120 - win.x.values, win.x.values)
        wy = np.where(opp, 80 - win.y.values, win.y.values)
        wzone = zone_of(wx, wy, band_cuts, lane_cuts, n_lanes)
        for K in raw_freq:
            for z in wzone[-K:]:
                raw_freq[K][int(z)] += 1

        # spark = first event of the goal's possession; turnover if prior possession was opponent
        gp = gm[gm.possession == gl.possession]
        spark = gp.iloc[0]
        prior = gm[gm.possession == gl.possession - 1]
        if len(prior) and prior.iloc[-1].possession_team != gl.possession_team:
            n_turnover_spark += 1
            regain[int(spark.zone)] += 1

        if len(chains) < 10 and len(win) >= 4:
            parts = []
            for (_, e), z in zip(win.iloc[-6:].iterrows(), wzone[-6:]):
                flip = "" if e.possession_team == scorer else "*"   # * = opponent's ball
                parts.append(f"{zlabel(int(z))}[{e.type[:4]}]{flip}")
            chains.append(" -> ".join(parts) + f" => GOAL {zlabel(int(gl.zone))}")

    grid_print("xT surface (Markov, clean possession — for reference)", xt)
    grid_print(f"RAW last-5 zone freq, turnovers included (% of actions)",
               raw_freq[5] / raw_freq[5].sum(), as_pct=True)
    grid_print(f"REGAIN/spark zone — where goal possessions were WON "
               f"({n_turnover_spark}/{n_used} goals sparked by a turnover) (% of those)",
               regain / max(regain.sum(), 1), as_pct=True)

    def rank(v):
        return np.argsort(np.argsort(v))
    print(f"\nSpearman(xT, raw last-5 freq) = {np.corrcoef(rank(xt), rank(raw_freq[5]))[0,1]:.3f}")
    print(f"Spearman(xT, regain zone)     = {np.corrcoef(rank(xt), rank(regain))[0,1]:.3f}")
    print(f"xT peak: {zlabel(int(np.argmax(xt)))}   "
          f"raw-5 peak: {zlabel(int(np.argmax(raw_freq[5])))}   "
          f"regain peak: {zlabel(int(np.argmax(regain)))}")
    # how much of the regain value sits in the WIDE/half-space lanes vs central
    wide = sum(regain[b * n_lanes + l] for b in range(n_bands) for l in (0, 1, 3, 4))
    print(f"regain-zone share in wide+half-space lanes: {wide/max(regain.sum(),1)*100:.0f}%  "
          f"(central lane: {(1-wide/max(regain.sum(),1))*100:.0f}%)")

    print("\nexample raw chains ( * = opponent had the ball -> turnover ):")
    for c in chains:
        print(f"  {c}")


if __name__ == "__main__":
    main()
