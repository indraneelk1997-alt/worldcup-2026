"""
_ea_attribute_buckets.py (S27) — decompose EA sub-attributes into role-aware
ratings. Locked S27 with the maintainer.

THREE role buckets (clean discriminators) + THREE cross-cutting quality bonuses
applied with role-dependent weights. This routes genuinely dual attributes
(heading, vision, dribbling) by emphasis rather than forcing a single home.

Role rating = BASE_W * role_base  +  BONUS_W * weighted_bonus
  weighted_bonus = (wS*Skills + wI*IQ + wP*Physical) / (wS+wI+wP)
  weights per role below (symmetric 3/2/1):
    Attack : Skills>Physical>IQ   Holding: IQ>Skills>Physical   Defense: Physical>IQ>Skills

Maintainer rationale: Attack = goal-scoring (heading_accuracy = hitting a
target, so it's attacking not defensive); Holding = keep possession; Defense =
win the ball back. Skills help attackers most; IQ helps holders most; Physical
helps defenders most.
"""
from __future__ import annotations

# --- role buckets (discriminators) ---
# role names: Attack / Possession (possession play) / Defense
ATTACK = ["finishing", "shot_power", "long_shots", "penalties", "heading_accuracy"]
POSSESSION = ["short_passing", "long_passing", "crossing", "ball_control", "vision"]
DEFENSE = ["def_awareness", "standing_tackle", "sliding_tackle", "interceptions"]

# --- bonus buckets (cross-cutting qualities) ---
SKILLS = ["volleys", "dribbling", "curve", "agility", "balance", "free_kick_accuracy"]
IQ = ["positioning", "composure", "reactions", "aggression"]
PHYSICAL = ["acceleration", "sprint_speed", "jumping", "stamina", "strength"]

# role -> (Skills, IQ, Physical) weights
WEIGHTS = {"Attack": (3, 1, 2), "Possession": (2, 3, 1), "Defense": (1, 2, 3)}

# base vs bonus split (tuning knob — base discriminators carry the role)
BASE_W = 0.75
BONUS_W = 0.25

ROLE_BASE = {"Attack": ATTACK, "Possession": POSSESSION, "Defense": DEFENSE}
ALL_ATTRS = ATTACK + POSSESSION + DEFENSE + SKILLS + IQ + PHYSICAL  # 29


def add_ratings(df):
    """Add Skills/IQ/Physical + AttackBase/HoldingBase/DefenseBase +
    Attack/Holding/Defense role ratings to an EA dataframe (vectorized)."""
    df = df.copy()
    df["Skills"] = df[SKILLS].mean(axis=1)
    df["IQ"] = df[IQ].mean(axis=1)
    df["Physical"] = df[PHYSICAL].mean(axis=1)
    for role, attrs in ROLE_BASE.items():
        df[f"{role}Base"] = df[attrs].mean(axis=1)
    for role, (ws, wi, wp) in WEIGHTS.items():
        bonus = (ws * df["Skills"] + wi * df["IQ"] + wp * df["Physical"]) / (ws + wi + wp)
        df[role] = BASE_W * df[f"{role}Base"] + BONUS_W * bonus
    return df
