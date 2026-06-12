"""
_probe_occupancy_coverage.py  (S32, DELETABLE)

Map the 23 StatsBomb positions -> our 23 position_codes and count open-play
events per (code, phase), so we see which codes are data-rich (derive empirical
kernel) vs sparse (lean on the hand prior). Set-pieces excluded. Read-only.

    uv run python src/load/v2_ingest/_probe_occupancy_coverage.py
"""
from __future__ import annotations
import duckdb
from derive_zone_xt import DB

# our code -> StatsBomb position(s) it pools from (symmetrised later)
CODE_SB = {
    "GK":  ["Goalkeeper"],
    "CB":  ["Center Back"],
    "DF":  ["Center Back"],                                   # generic -> CB prior
    "LCB": ["Left Center Back"], "RCB": ["Right Center Back"],
    "LB":  ["Left Back"], "RB": ["Right Back"],
    "LWB": ["Left Wing Back"], "RWB": ["Right Wing Back"],
    "DM":  ["Center Defensive Midfield", "Left Defensive Midfield", "Right Defensive Midfield"],
    "MF":  ["Center Defensive Midfield", "Left Center Midfield", "Right Center Midfield"],  # generic
    "CM":  ["Left Center Midfield", "Right Center Midfield"],  # no direct SB 'Center Midfield'
    "LCM": ["Left Center Midfield"], "RCM": ["Right Center Midfield"],
    "LM":  ["Left Midfield"], "RM": ["Right Midfield"],
    "CAM": ["Center Attacking Midfield"],
    "LAM": ["Left Attacking Midfield"], "RAM": ["Right Attacking Midfield"],
    "LW":  ["Left Wing"], "RW": ["Right Wing"],
    "ST":  ["Center Forward", "Left Center Forward", "Right Center Forward"],
    "FW":  ["Center Forward"],
}
ONBALL = ("Pass", "Carry", "Ball Receipt*", "Dribble", "Shot")
DEFACT = ("Pressure", "Duel", "Interception", "Block", "Clearance", "Ball Recovery", "Foul Committed")
SETPIECE = ("From Corner", "From Free Kick")


def main():
    con = duckdb.connect(str(DB), read_only=True)

    def count(positions, types):
        pl = "','".join(positions); tl = "','".join(types); sp = "','".join(SETPIECE)
        return con.execute(f"""
            SELECT COUNT(*) FROM statsbomb_event
            WHERE position IN ('{pl}') AND type IN ('{tl}')
              AND (play_pattern IS NULL OR play_pattern NOT IN ('{sp}'))
        """).fetchone()[0]

    print(f"{'code':4} {'on-ball':>8} {'defence':>8}  flag   SB position(s)")
    for code, sbs in CODE_SB.items():
        if code == "GK":
            print(f"{code:4} {'--':>8} {'--':>8}  (GK track separate)"); continue
        on, de = count(sbs, ONBALL), count(sbs, DEFACT)
        flag = "" if (on >= 3000 and de >= 600) else "SPARSE -> prior"
        print(f"{code:4} {on:8d} {de:8d}  {flag:14} {', '.join(sbs)}")
    con.close()


if __name__ == "__main__":
    main()
