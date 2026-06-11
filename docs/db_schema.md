# DuckDB schema reference

_Generated: 2026-06-11T19:13:20_  
_DB: `data/processed/worldcup.duckdb`_  
_Tables: 29_  


This file is auto-generated. Do not edit by hand. Regenerate with:
```
uv run python src/tools/dump_db_schema.py
```

---

## Tables

### `best_xi`

**Rows**: 660

| Column | Type | Nullable | PK |
|---|---|---|---|
| `season` | `VARCHAR` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `formation` | `VARCHAR` | NO | ✓ |
| `rank` | `INTEGER` | NO | ✓ |
| `slot_no` | `INTEGER` | NO | ✓ |
| `player_id` | `INTEGER` | NO |  |
| `position_class` | `VARCHAR` | NO |  |
| `minutes` | `INTEGER` | NO |  |
| `selection_score` | `DOUBLE` | YES |  |
| `total_xi_score` | `DOUBLE` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`formation`) → `formations` (`formation`)
- (`player_id`) → `players` (`player_id`)

**Sample row**:

```
  season = '2025-2026'
  team = 'Arsenal'
  formation = '4-2-3-1'
  rank = 1
  slot_no = 1
  player_id = 9676
  position_class = 'GK'
  minutes = 3330
  selection_score = None
  total_xi_score = 5.606012760093487
```

### `club_elo`

**Rows**: 4,478

| Column | Type | Nullable | PK |
|---|---|---|---|
| `club` | `VARCHAR` | NO | ✓ |
| `country` | `VARCHAR` | NO |  |
| `level` | `INTEGER` | NO |  |
| `elo` | `DOUBLE` | NO |  |
| `valid_from` | `DATE` | NO | ✓ |
| `valid_to` | `DATE` | NO |  |

**Declared foreign keys**: none

**Sample row**:

```
  club = 'Arsenal'
  country = 'ENG'
  level = 1
  elo = 1946.90283203
  valid_from = datetime.date(2024, 5, 23)
  valid_to = datetime.date(2024, 8, 17)
```

### `ea_fc26_player`

**Rows**: 16,228

| Column | Type | Nullable | PK |
|---|---|---|---|
| `ea_id` | `INTEGER` | NO | ✓ |
| `name` | `VARCHAR` | NO |  |
| `name_norm` | `VARCHAR` | YES |  |
| `ovr` | `INTEGER` | YES |  |
| `position` | `VARCHAR` | YES |  |
| `position_class` | `VARCHAR` | YES |  |
| `alt_positions` | `VARCHAR` | YES |  |
| `nation_name` | `VARCHAR` | YES |  |
| `nation_code` | `VARCHAR` | YES |  |
| `league` | `VARCHAR` | YES |  |
| `club` | `VARCHAR` | YES |  |
| `age` | `INTEGER` | YES |  |
| `preferred_foot` | `VARCHAR` | YES |  |
| `weak_foot` | `INTEGER` | YES |  |
| `skill_moves` | `INTEGER` | YES |  |
| `height_cm` | `INTEGER` | YES |  |
| `weight_kg` | `INTEGER` | YES |  |
| `ea_pace` | `INTEGER` | YES |  |
| `ea_shooting` | `INTEGER` | YES |  |
| `ea_passing` | `INTEGER` | YES |  |
| `ea_dribbling` | `INTEGER` | YES |  |
| `ea_defending` | `INTEGER` | YES |  |
| `ea_physical` | `INTEGER` | YES |  |
| `acceleration` | `INTEGER` | YES |  |
| `sprint_speed` | `INTEGER` | YES |  |
| `positioning` | `INTEGER` | YES |  |
| `finishing` | `INTEGER` | YES |  |
| `shot_power` | `INTEGER` | YES |  |
| `long_shots` | `INTEGER` | YES |  |
| `volleys` | `INTEGER` | YES |  |
| `penalties` | `INTEGER` | YES |  |
| `vision` | `INTEGER` | YES |  |
| `crossing` | `INTEGER` | YES |  |
| `free_kick_accuracy` | `INTEGER` | YES |  |
| `short_passing` | `INTEGER` | YES |  |
| `long_passing` | `INTEGER` | YES |  |
| `curve` | `INTEGER` | YES |  |
| `dribbling` | `INTEGER` | YES |  |
| `agility` | `INTEGER` | YES |  |
| `balance` | `INTEGER` | YES |  |
| `reactions` | `INTEGER` | YES |  |
| `ball_control` | `INTEGER` | YES |  |
| `composure` | `INTEGER` | YES |  |
| `interceptions` | `INTEGER` | YES |  |
| `heading_accuracy` | `INTEGER` | YES |  |
| `def_awareness` | `INTEGER` | YES |  |
| `standing_tackle` | `INTEGER` | YES |  |
| `sliding_tackle` | `INTEGER` | YES |  |
| `jumping` | `INTEGER` | YES |  |
| `stamina` | `INTEGER` | YES |  |
| `strength` | `INTEGER` | YES |  |
| `aggression` | `INTEGER` | YES |  |
| `gk_diving` | `INTEGER` | YES |  |
| `gk_handling` | `INTEGER` | YES |  |
| `gk_kicking` | `INTEGER` | YES |  |
| `gk_positioning` | `INTEGER` | YES |  |
| `gk_reflexes` | `INTEGER` | YES |  |
| `play_style_raw` | `VARCHAR` | YES |  |
| `source_url` | `VARCHAR` | YES |  |
| `card_url` | `VARCHAR` | YES |  |
| `source` | `VARCHAR` | YES |  |
| `ingested_at` | `TIMESTAMP` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  ea_id = 203376
  name = 'Virgil van Dijk'
  name_norm = 'virgil van dijk'
  ovr = 90
  position = 'CB'
  position_class = 'DEF'
  alt_positions = None
  nation_name = 'Holland'
  nation_code = None
  league = 'Premier League'
  club = 'Liverpool'
  age = 34
  preferred_foot = 'Right'
  weak_foot = 3
  skill_moves = 2
  height_cm = 193
  weight_kg = 92
  ea_pace = 73
  ea_shooting = 60
  ea_passing = 72
  ea_dribbling = 72
  ea_defending = 90
  ea_physical = 87
  acceleration = 66
  sprint_speed = 78
  positioning = 47
  finishing = 52
  shot_power = 81
  long_shots = 64
  volleys = 45
  penalties = 62
  vision = 53
  crossing = 70
  free_kick_accuracy = 70
  short_passing = 80
  long_passing = 83
  curve = 60
  dribbling = 70
  agility = 54
  balance = 50
  reactions = 90
  ball_control = 77
  composure = 90
  interceptions = 91
  heading_accuracy = 88
  def_awareness = 91
  standing_tackle = 91
  sliding_tackle = 87
  jumping = 89
  stamina = 75
  strength = 93
  aggression = 85
  gk_diving = None
  gk_handling = None
  gk_kicking = None
  gk_positioning = None
  gk_reflexes = None
  play_style_raw = "['Intercept+', 'Aerial Fortress', 'Anticipate', 'Bruiser', 'Jockey', 'Pinged...
  source_url = 'https://www.ea.com/games/ea-sports-fc/ratings/player-ratings/virgil-van-dijk...
  card_url = 'https://ratings-images-prod.pulse.ea.com/FC26/components/items/203376_en.webp'
  source = 'eafc26'
  ingested_at = datetime.datetime(2026, 6, 11, 12, 31, 17, 158494)
```

### `ea_fc26_playstyle`

**Rows**: 15,032

| Column | Type | Nullable | PK |
|---|---|---|---|
| `ea_id` | `INTEGER` | NO | ✓ |
| `playstyle` | `VARCHAR` | NO | ✓ |
| `tier` | `VARCHAR` | NO |  |

**Declared foreign keys**: none

**Sample row**:

```
  ea_id = 209331
  playstyle = 'Finesse Shot'
  tier = 'plus'
```

### `fixture_lineups`

**Rows**: 242

| Column | Type | Nullable | PK |
|---|---|---|---|
| `scenario_id` | `INTEGER` | NO | ✓ |
| `side` | `VARCHAR` | NO | ✓ |
| `slot_no` | `INTEGER` | NO | ✓ |
| `player_id` | `INTEGER` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`player_id`) → `players` (`player_id`)
- (`scenario_id`) → `lineup_scenarios` (`scenario_id`)
- (`scenario_id`, `side`) → `scenario_teams` (`scenario_id`, `side`)

**Sample row**:

```
  scenario_id = 1
  side = 'home'
  slot_no = 1
  player_id = 618
```

### `fixtures`

**Rows**: 11

| Column | Type | Nullable | PK |
|---|---|---|---|
| `fixture_id` | `VARCHAR` | NO | ✓ |
| `season` | `VARCHAR` | NO |  |
| `match_date` | `DATE` | NO |  |
| `home_team` | `VARCHAR` | NO |  |
| `away_team` | `VARCHAR` | NO |  |
| `matchday` | `INTEGER` | YES |  |
| `league` | `VARCHAR` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  fixture_id = '2024-25_ars_liv_trial'
  season = '2024-2025'
  match_date = datetime.date(2025, 5, 11)
  home_team = 'Arsenal'
  away_team = 'Liverpool'
  matchday = None
  league = 'ENG-Premier League'
```

### `formation_slots`

**Rows**: 110

| Column | Type | Nullable | PK |
|---|---|---|---|
| `formation` | `VARCHAR` | NO | ✓ |
| `slot_no` | `INTEGER` | NO | ✓ |
| `position_code` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`formation`) → `formations` (`formation`)
- (`position_code`) → `positions` (`position_code`)

**Sample row**:

```
  formation = '4-3-3'
  slot_no = 1
  position_code = 'GK'
```

### `formations`

**Rows**: 10

| Column | Type | Nullable | PK |
|---|---|---|---|
| `formation` | `VARCHAR` | NO | ✓ |

**Declared foreign keys**: none

**Sample row**:

```
  formation = '4-3-3'
```

### `games`

**Rows**: 4,260

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO |  |
| `match_date` | `DATE` | NO |  |
| `home_team` | `VARCHAR` | NO |  |
| `away_team` | `VARCHAR` | NO |  |
| `league` | `VARCHAR` | YES |  |
| `source` | `VARCHAR` | YES |  |
| `source_game_id` | `VARCHAR` | YES |  |
| `stage` | `VARCHAR` | YES |  |
| `venue` | `VARCHAR` | YES |  |
| `home_goals` | `INTEGER` | YES |  |
| `away_goals` | `INTEGER` | YES |  |
| `home_pens` | `INTEGER` | YES |  |
| `away_pens` | `INTEGER` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  game_id = 26602
  season = '2024-2025'
  match_date = datetime.date(2024, 8, 16)
  home_team = 'Manchester United'
  away_team = 'Fulham'
  league = 'ENG-Premier League'
  source = 'understat'
  source_game_id = None
  stage = None
  venue = None
  home_goals = None
  away_goals = None
  home_pens = None
  away_pens = None
```

### `league_averages_v103`

**Rows**: 3

| Column | Type | Nullable | PK |
|---|---|---|---|
| `season` | `VARCHAR` | NO | ✓ |
| `league_avg_xg` | `DOUBLE` | NO |  |
| `league_avg_ppda` | `DOUBLE` | NO |  |
| `n_team_matches` | `INTEGER` | NO |  |
| `created_at` | `TIMESTAMP` | YES |  |
| `league` | `VARCHAR` | NO |  |

**Declared foreign keys**: none

**Sample row**:

```
  season = '2024-2025'
  league_avg_xg = 1.6009302259210512
  league_avg_ppda = 12.55532680261568
  n_team_matches = 760
  created_at = datetime.datetime(2026, 5, 22, 16, 1, 34, 240711)
  league = 'ENG-Premier League'
```

### `lineup_scenarios`

**Rows**: 11

| Column | Type | Nullable | PK |
|---|---|---|---|
| `scenario_id` | `INTEGER` | NO | ✓ |
| `fixture_id` | `VARCHAR` | NO |  |
| `scenario_type` | `VARCHAR` | NO |  |
| `label` | `VARCHAR` | YES |  |
| `created_at` | `TIMESTAMP` | YES |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`fixture_id`) → `fixtures` (`fixture_id`)

**Sample row**:

```
  scenario_id = 1
  fixture_id = '2024-25_ars_liv_trial'
  scenario_type = 'legacy_v1.01'
  label = 'ARS vs LIV trial (V1.01 baseline, pre-formation)'
  created_at = datetime.datetime(2026, 5, 20, 19, 5, 22, 860431)
```

### `md38_evaluation_b12_b2`

**Rows**: 20

| Column | Type | Nullable | PK |
|---|---|---|---|
| `fixture_id` | `VARCHAR` | NO | ✓ |
| `model_version` | `VARCHAR` | NO | ✓ |
| `actual_home_goals` | `INTEGER` | NO |  |
| `actual_away_goals` | `INTEGER` | NO |  |
| `actual_outcome` | `VARCHAR` | NO |  |
| `p_home_win` | `DOUBLE` | NO |  |
| `p_draw` | `DOUBLE` | NO |  |
| `p_away_win` | `DOUBLE` | NO |  |
| `p_actual_scoreline` | `DOUBLE` | NO |  |
| `p_actual_outcome` | `DOUBLE` | NO |  |
| `log_loss_scoreline` | `DOUBLE` | NO |  |
| `log_loss_outcome` | `DOUBLE` | NO |  |
| `brier_outcome` | `DOUBLE` | NO |  |
| `evaluated_at` | `TIMESTAMP` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`fixture_id`) → `fixtures` (`fixture_id`)
- (`fixture_id`, `model_version`) → `md38_predictions_b12` (`fixture_id`, `model_version`)

**Sample row**:

```
  fixture_id = '2025-26_md38_bri_mun'
  model_version = 'B1.2_v103_poisson_indep'
  actual_home_goals = 0
  actual_away_goals = 3
  actual_outcome = 'A'
  p_home_win = 0.35437732708073766
  p_draw = 0.24307755525107916
  p_away_win = 0.40254511766818335
  p_actual_scoreline = 0.031206987919421676
  p_actual_outcome = 0.40254511766818335
  log_loss_scoreline = 3.4671132374682987
  log_loss_outcome = 0.9099480948199868
  brier_outcome = 0.5416223242378544
  evaluated_at = datetime.datetime(2026, 5, 25, 9, 4, 25, 305698)
```

### `md38_predictions_b12`

**Rows**: 20

| Column | Type | Nullable | PK |
|---|---|---|---|
| `fixture_id` | `VARCHAR` | NO | ✓ |
| `home_team` | `VARCHAR` | NO |  |
| `away_team` | `VARCHAR` | NO |  |
| `xg_home` | `DOUBLE` | NO |  |
| `xg_away` | `DOUBLE` | NO |  |
| `p_home_win` | `DOUBLE` | NO |  |
| `p_draw` | `DOUBLE` | NO |  |
| `p_away_win` | `DOUBLE` | NO |  |
| `expected_home_goals` | `DOUBLE` | NO |  |
| `expected_away_goals` | `DOUBLE` | NO |  |
| `most_likely_score_home` | `INTEGER` | NO |  |
| `most_likely_score_away` | `INTEGER` | NO |  |
| `most_likely_score_prob` | `DOUBLE` | NO |  |
| `prob_mass_truncated` | `DOUBLE` | NO |  |
| `model_version` | `VARCHAR` | NO | ✓ |
| `predicted_at` | `TIMESTAMP` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`fixture_id`) → `fixtures` (`fixture_id`)

**Sample row**:

```
  fixture_id = '2025-26_md38_bri_mun'
  home_team = 'Brighton'
  away_team = 'Manchester United'
  xg_home = 1.441004179791372
  xg_away = 1.5505823137621941
  p_home_win = 0.35437732708073766
  p_draw = 0.24307755525107916
  p_away_win = 0.40254511766818335
  expected_home_goals = 1.440130952155806
  expected_away_goals = 1.5491755842036734
  most_likely_score_home = 1
  most_likely_score_away = 1
  most_likely_score_prob = 0.11222217761622406
  prob_mass_truncated = 0.0003410271195978254
  model_version = 'B1.2_v103_poisson_indep'
  predicted_at = datetime.datetime(2026, 5, 22, 18, 16, 27, 274552)
```

### `md38_score_grid_b12`

**Rows**: 1,280

| Column | Type | Nullable | PK |
|---|---|---|---|
| `fixture_id` | `VARCHAR` | NO | ✓ |
| `model_version` | `VARCHAR` | NO | ✓ |
| `home_goals` | `INTEGER` | NO | ✓ |
| `away_goals` | `INTEGER` | NO | ✓ |
| `probability` | `DOUBLE` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`fixture_id`, `model_version`) → `md38_predictions_b12` (`fixture_id`, `model_version`)

**Sample row**:

```
  fixture_id = '2025-26_md38_bri_mun'
  model_version = 'B1.2_v103_poisson_indep'
  home_goals = 0
  away_goals = 0
  probability = 0.0502248473167415
```

### `model_parameters_v103`

**Rows**: 1

| Column | Type | Nullable | PK |
|---|---|---|---|
| `parameter_name` | `VARCHAR` | NO | ✓ |
| `model_version` | `VARCHAR` | NO | ✓ |
| `value` | `DOUBLE` | NO |  |
| `n_matches_used` | `INTEGER` | NO |  |
| `log_likelihood` | `DOUBLE` | NO |  |
| `ll_vs_baseline` | `DOUBLE` | NO |  |
| `calibrated_at` | `TIMESTAMP` | NO |  |
| `notes` | `VARCHAR` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  parameter_name = 'dc_rho'
  model_version = 'B2_v103_dc_post_hoc'
  value = -0.0895895662053919
  n_matches_used = 750
  log_likelihood = -2167.414170616027
  ll_vs_baseline = 1.9193207427033485
  calibrated_at = datetime.datetime(2026, 5, 22, 19, 20, 4, 262379)
  notes = 'MLE on B1.2 xG inputs, 2024-25 + 2025-26 played matches. Path Z: post-proces...
```

### `player_match_fbref`

**Rows**: 32,873

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `player_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO |  |
| `team` | `VARCHAR` | NO |  |
| `league` | `VARCHAR` | NO |  |
| `position` | `VARCHAR` | YES |  |
| `effective_position` | `VARCHAR` | YES |  |
| `position_id` | `INTEGER` | YES |  |
| `jersey_number` | `INTEGER` | YES |  |
| `nation` | `VARCHAR` | YES |  |
| `minutes` | `INTEGER` | YES |  |
| `goals` | `INTEGER` | YES |  |
| `assists` | `INTEGER` | YES |  |
| `pens_made` | `INTEGER` | YES |  |
| `pens_att` | `INTEGER` | YES |  |
| `shots` | `INTEGER` | YES |  |
| `shots_on_target` | `INTEGER` | YES |  |
| `yellow_cards` | `INTEGER` | YES |  |
| `red_cards` | `INTEGER` | YES |  |
| `fouls` | `INTEGER` | YES |  |
| `fouled` | `INTEGER` | YES |  |
| `offsides` | `INTEGER` | YES |  |
| `crosses` | `INTEGER` | YES |  |
| `tackles_won` | `INTEGER` | YES |  |
| `interceptions` | `INTEGER` | YES |  |
| `own_goals` | `INTEGER` | YES |  |
| `pens_won` | `INTEGER` | YES |  |
| `pens_conceded` | `INTEGER` | YES |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`game_id`) → `games` (`game_id`)
- (`player_id`) → `players` (`player_id`)

**Sample row**:

```
  game_id = 10000000
  player_id = 50000023
  season = '2024-2025'
  team = 'Bayern Munich'
  league = 'UEFA-Champions League'
  position = 'DM'
  effective_position = 'DM'
  position_id = None
  jersey_number = 45
  nation = 'GER'
  minutes = 90
  goals = 0
  assists = 0
  pens_made = 0
  pens_att = 0
  shots = 0
  shots_on_target = 0
  yellow_cards = 0
  red_cards = 0
  fouls = 2
  fouled = 1
  offsides = 0
  crosses = 0
  tackles_won = 0
  interceptions = 0
  own_goals = 0
  pens_won = None
  pens_conceded = None
```

### `player_match_stats`

**Rows**: 99,079

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `player_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO |  |
| `team` | `VARCHAR` | NO |  |
| `position` | `VARCHAR` | NO |  |
| `effective_position` | `VARCHAR` | NO |  |
| `position_id` | `INTEGER` | NO |  |
| `minutes` | `INTEGER` | NO |  |
| `goals` | `INTEGER` | NO |  |
| `own_goals` | `INTEGER` | NO |  |
| `shots` | `INTEGER` | NO |  |
| `xg` | `DOUBLE` | NO |  |
| `xg_chain` | `DOUBLE` | NO |  |
| `xg_buildup` | `DOUBLE` | NO |  |
| `assists` | `INTEGER` | NO |  |
| `xa` | `DOUBLE` | NO |  |
| `key_passes` | `INTEGER` | NO |  |
| `yellow_cards` | `INTEGER` | NO |  |
| `red_cards` | `INTEGER` | NO |  |
| `league` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`game_id`) → `games` (`game_id`)
- (`player_id`) → `players` (`player_id`)

**Sample row**:

```
  game_id = 26602
  player_id = 900
  season = '2024-2025'
  team = 'Fulham'
  position = 'AMR'
  effective_position = 'AMR'
  position_id = 11
  minutes = 79
  goals = 0
  own_goals = 0
  shots = 3
  xg = 0.11462824046611786
  xg_chain = 0.1360686719417572
  xg_buildup = 0.021440427750349045
  assists = 0
  xa = 0.0
  key_passes = 0
  yellow_cards = 0
  red_cards = 0
  league = 'ENG-Premier League'
```

### `player_positions`

**Rows**: 1,042

| Column | Type | Nullable | PK |
|---|---|---|---|
| `player_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `position_class` | `VARCHAR` | NO | ✓ |
| `priority` | `INTEGER` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`player_id`) → `players` (`player_id`)

**Sample row**:

```
  player_id = 7298
  season = '2024-2025'
  team = 'Arsenal'
  position_class = 'DEF'
  priority = 1
```

### `player_positions_v103`

**Rows**: 2,014

| Column | Type | Nullable | PK |
|---|---|---|---|
| `player_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `position_code` | `VARCHAR` | NO | ✓ |
| `position_class` | `VARCHAR` | NO |  |
| `minutes_in_role` | `INTEGER` | NO |  |
| `n_matches` | `INTEGER` | NO |  |
| `priority` | `INTEGER` | NO |  |
| `position_source` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`player_id`) → `players` (`player_id`)
- (`position_code`) → `positions` (`position_code`)

**Sample row**:

```
  player_id = 10696
  season = '2024-2025'
  team = 'Manchester United'
  position_code = 'CB'
  position_class = 'DEF'
  minutes_in_role = 934
  n_matches = 11
  priority = 1
  position_source = 'per_match'
```

### `player_season_stats`

**Rows**: 793

| Column | Type | Nullable | PK |
|---|---|---|---|
| `player_id` | `INTEGER` | NO | ✓ |
| `season` | `VARCHAR` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `team_id` | `INTEGER` | YES |  |
| `position` | `VARCHAR` | YES |  |
| `matches` | `INTEGER` | YES |  |
| `minutes` | `INTEGER` | NO |  |
| `goals` | `INTEGER` | YES |  |
| `assists` | `INTEGER` | YES |  |
| `np_xg` | `DOUBLE` | YES |  |
| `xa` | `DOUBLE` | YES |  |
| `rating_per_90` | `DOUBLE` | YES |  |
| `shrunk_form` | `DOUBLE` | YES |  |
| `shrunk_consistency` | `DOUBLE` | YES |  |
| `position_class` | `VARCHAR` | YES |  |
| `shrunk_form_eb` | `DOUBLE` | YES |  |
| `shrunk_consistency_eb` | `DOUBLE` | YES |  |
| `primary_position_code_v103` | `VARCHAR` | YES |  |
| `primary_position_class_v103` | `VARCHAR` | YES |  |
| `shrunk_form_eb_class` | `DOUBLE` | YES |  |
| `shrunk_consistency_eb_class` | `DOUBLE` | YES |  |
| `league` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`player_id`) → `players` (`player_id`)

**Sample row**:

```
  player_id = 7322
  season = '2024-2025'
  team = 'Arsenal'
  team_id = 83
  position = 'F M S'
  matches = 25
  minutes = 1763
  goals = 6
  assists = 10
  np_xg = 8.182253051549196
  xa = 11.583731275051832
  rating_per_90 = 1.0090406065763429
  shrunk_form = 0.7488086340796463
  shrunk_consistency = 0.7095943685212551
  position_class = 'FWD'
  shrunk_form_eb = 0.927471131544744
  shrunk_consistency_eb = 0.7873605675129416
  primary_position_code_v103 = 'RW'
  primary_position_class_v103 = 'FWD'
  shrunk_form_eb_class = 0.8740806073539971
  shrunk_consistency_eb_class = 0.7719511861294119
  league = 'ENG-Premier League'
```

### `players`

**Rows**: 7,537

| Column | Type | Nullable | PK |
|---|---|---|---|
| `player_id` | `INTEGER` | NO | ✓ |
| `player_name` | `VARCHAR` | NO |  |
| `player_dob` | `DATE` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  player_id = 447
  player_name = 'Kevin De Bruyne'
  player_dob = None
```

### `positions`

**Rows**: 23

| Column | Type | Nullable | PK |
|---|---|---|---|
| `position_code` | `VARCHAR` | NO | ✓ |
| `position_class` | `VARCHAR` | NO |  |
| `flank` | `VARCHAR` | NO |  |
| `position_class_v103` | `VARCHAR` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  position_code = 'GK'
  position_class = 'GK'
  flank = 'C'
  position_class_v103 = 'GK'
```

### `predictions`

**Rows**: 21

| Column | Type | Nullable | PK |
|---|---|---|---|
| `prediction_id` | `VARCHAR` | NO | ✓ |
| `scenario_id` | `INTEGER` | NO |  |
| `model_version` | `VARCHAR` | NO |  |
| `run_timestamp` | `TIMESTAMP` | NO |  |
| `n_simulations` | `INTEGER` | NO |  |
| `rng_seed` | `INTEGER` | NO |  |
| `base_goals` | `DOUBLE` | NO |  |
| `k_param` | `DOUBLE` | NO |  |
| `home_strength` | `DOUBLE` | NO |  |
| `away_strength` | `DOUBLE` | NO |  |
| `xg_home` | `DOUBLE` | NO |  |
| `xg_away` | `DOUBLE` | NO |  |
| `p_home_win` | `DOUBLE` | NO |  |
| `p_draw` | `DOUBLE` | NO |  |
| `p_away_win` | `DOUBLE` | NO |  |
| `avg_home_goals` | `DOUBLE` | NO |  |
| `avg_away_goals` | `DOUBLE` | NO |  |
| `modal_scoreline` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`scenario_id`) → `lineup_scenarios` (`scenario_id`)

**Sample row**:

```
  prediction_id = '2024-25_ars_liv_trial_v1.01_20260511_135909'
  scenario_id = 1
  model_version = 'v1.01'
  run_timestamp = datetime.datetime(2026, 5, 11, 13, 59, 9, 630527)
  n_simulations = 10000
  rng_seed = 42
  base_goals = 1.4
  k_param = 1.0
  home_strength = 5.8932655121481545
  away_strength = 6.2268116754036775
  xg_home = 1.066453836744477
  xg_away = 1.733546163255523
  p_home_win = 0.2301
  p_draw = 0.2463
  p_away_win = 0.5236
  avg_home_goals = 1.0626
  avg_away_goals = 1.7334
  modal_scoreline = '1-1'
```

### `scenario_teams`

**Rows**: 22

| Column | Type | Nullable | PK |
|---|---|---|---|
| `scenario_id` | `INTEGER` | NO | ✓ |
| `side` | `VARCHAR` | NO | ✓ |
| `team` | `VARCHAR` | NO |  |
| `formation` | `VARCHAR` | YES |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`formation`) → `formations` (`formation`)
- (`scenario_id`) → `lineup_scenarios` (`scenario_id`)

**Sample row**:

```
  scenario_id = 1
  side = 'home'
  team = 'Arsenal'
  formation = None
```

### `team_match_fbref`

**Rows**: 2,124

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `side` | `VARCHAR` | YES |  |
| `season` | `VARCHAR` | NO |  |
| `opponent` | `VARCHAR` | YES |  |
| `league` | `VARCHAR` | NO |  |
| `goals` | `INTEGER` | YES |  |
| `opponent_goals` | `INTEGER` | YES |  |
| `result` | `VARCHAR` | YES |  |
| `possession` | `DOUBLE` | YES |  |
| `attendance` | `INTEGER` | YES |  |
| `captain` | `VARCHAR` | YES |  |
| `formation` | `VARCHAR` | YES |  |
| `opp_formation` | `VARCHAR` | YES |  |
| `referee` | `VARCHAR` | YES |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`game_id`) → `games` (`game_id`)

**Sample row**:

```
  game_id = 10000012
  team = 'Arsenal'
  side = 'away'
  season = '2024-2025'
  opponent = 'Atalanta'
  league = 'UEFA-Champions League'
  goals = 0
  opponent_goals = 0
  result = 'D'
  possession = 46.0
  attendance = 22858
  captain = 'Gabriel Jesus'
  formation = '4-3-3'
  opp_formation = '3-4-3'
  referee = 'Clément Turpin'
```

### `team_match_predictions_b12`

**Rows**: 1,500

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `season` | `VARCHAR` | NO |  |
| `side` | `VARCHAR` | NO |  |
| `opponent` | `VARCHAR` | NO |  |
| `predicted_xg` | `DOUBLE` | NO |  |
| `attack_x_opp_defense` | `DOUBLE` | NO |  |
| `side_multiplier` | `DOUBLE` | NO |  |
| `model_version` | `VARCHAR` | NO | ✓ |
| `created_at` | `TIMESTAMP` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  game_id = 26602
  team = 'Manchester United'
  season = '2024-2025'
  side = 'home'
  opponent = 'Fulham'
  predicted_xg = 1.2726251967512805
  attack_x_opp_defense = 1.2120239969059814
  side_multiplier = 1.05
  model_version = 'B1.2_v103'
  created_at = datetime.datetime(2026, 5, 22, 16, 48, 50, 955077)
```

### `team_match_stats`

**Rows**: 6,394

| Column | Type | Nullable | PK |
|---|---|---|---|
| `game_id` | `INTEGER` | NO | ✓ |
| `team` | `VARCHAR` | NO | ✓ |
| `side` | `VARCHAR` | NO |  |
| `season` | `VARCHAR` | NO |  |
| `opponent` | `VARCHAR` | NO |  |
| `points` | `INTEGER` | NO |  |
| `expected_points` | `DOUBLE` | NO |  |
| `goals` | `INTEGER` | NO |  |
| `opponent_goals` | `INTEGER` | NO |  |
| `xg` | `DOUBLE` | NO |  |
| `opponent_xg` | `DOUBLE` | NO |  |
| `np_xg` | `DOUBLE` | NO |  |
| `opponent_np_xg` | `DOUBLE` | NO |  |
| `np_xg_difference` | `DOUBLE` | NO |  |
| `ppda` | `DOUBLE` | NO |  |
| `opponent_ppda` | `DOUBLE` | NO |  |
| `deep_completions` | `INTEGER` | NO |  |
| `opponent_deep_completions` | `INTEGER` | NO |  |
| `league` | `VARCHAR` | NO |  |

**Declared foreign keys** (per `duckdb_constraints()`):

- (`game_id`) → `games` (`game_id`)

**Sample row**:

```
  game_id = 26602
  team = 'Manchester United'
  side = 'home'
  season = '2024-2025'
  opponent = 'Fulham'
  points = 3
  expected_points = 2.5696
  goals = 1
  opponent_goals = 0
  xg = 2.04268
  opponent_xg = 0.418711
  np_xg = 2.04268
  opponent_np_xg = 0.418711
  np_xg_difference = 1.6239689999999998
  ppda = 7.379310344827586
  opponent_ppda = 10.833333333333334
  deep_completions = 7
  opponent_deep_completions = 3
  league = 'ENG-Premier League'
```

### `team_season_strength_v103`

**Rows**: 40

| Column | Type | Nullable | PK |
|---|---|---|---|
| `team` | `VARCHAR` | NO | ✓ |
| `season` | `VARCHAR` | NO | ✓ |
| `n_matches` | `INTEGER` | NO |  |
| `avg_xg_for` | `DOUBLE` | NO |  |
| `avg_xg_allowed` | `DOUBLE` | NO |  |
| `avg_ppda_pressing` | `DOUBLE` | NO |  |
| `created_at` | `TIMESTAMP` | YES |  |
| `league` | `VARCHAR` | NO |  |

**Declared foreign keys**: none

**Sample row**:

```
  team = 'Arsenal'
  season = '2024-2025'
  n_matches = 38
  avg_xg_for = 1.9360501315789478
  avg_xg_allowed = 1.0521016236842107
  avg_ppda_pressing = 9.43274286965661
  created_at = datetime.datetime(2026, 5, 22, 16, 1, 34, 228139)
  league = 'ENG-Premier League'
```

### `wc2026_squad`

**Rows**: 1,247

| Column | Type | Nullable | PK |
|---|---|---|---|
| `squad_row_id` | `INTEGER` | NO | ✓ |
| `nation_name` | `VARCHAR` | NO |  |
| `nation_code` | `VARCHAR` | YES |  |
| `player_name` | `VARCHAR` | NO |  |
| `name_norm` | `VARCHAR` | NO |  |
| `dob` | `DATE` | YES |  |
| `club` | `VARCHAR` | YES |  |
| `position_class` | `VARCHAR` | NO |  |
| `shirt_no` | `INTEGER` | YES |  |
| `caps` | `INTEGER` | YES |  |
| `intl_goals` | `INTEGER` | YES |  |
| `is_captain` | `BOOLEAN` | YES |  |
| `our_player_id` | `INTEGER` | YES |  |
| `link_method` | `VARCHAR` | YES |  |
| `link_confidence` | `DOUBLE` | YES |  |
| `ea_id` | `INTEGER` | YES |  |
| `ea_link_method` | `VARCHAR` | YES |  |
| `ea_link_confidence` | `DOUBLE` | YES |  |
| `source` | `VARCHAR` | YES |  |
| `source_url` | `VARCHAR` | YES |  |
| `ingested_at` | `TIMESTAMP` | YES |  |

**Declared foreign keys**: none

**Sample row**:

```
  squad_row_id = 1
  nation_name = 'Czech Republic'
  nation_code = 'CZE'
  player_name = 'Matěj Kovář'
  name_norm = 'matej kovar'
  dob = datetime.date(2000, 5, 17)
  club = 'PSV Eindhoven'
  position_class = 'GK'
  shirt_no = 1
  caps = 20
  intl_goals = 0
  is_captain = False
  our_player_id = None
  link_method = None
  link_confidence = None
  ea_id = None
  ea_link_method = None
  ea_link_confidence = None
  source = 'wikipedia'
  source_url = 'https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads'
  ingested_at = datetime.datetime(2026, 6, 11, 12, 22, 32, 522418)
```

---

## Column-name graph

> These column names appear in 2+ tables. Some are real FK relationships (declared or NOT — `duckdb_constraints()` is known to miss some, see S14 carry-forward). Some are dimensional values that happen to share names (e.g. `season`, `model_version`). Inspect manually.

### `season` (13 tables)

- `best_xi` *(PK)*
- `fixtures`
- `games`
- `league_averages_v103` *(PK)*
- `player_match_fbref`
- `player_match_stats`
- `player_positions` *(PK)*
- `player_positions_v103` *(PK)*
- `player_season_stats` *(PK)*
- `team_match_fbref`
- `team_match_predictions_b12`
- `team_match_stats`
- `team_season_strength_v103` *(PK)*

### `team` (11 tables)

- `best_xi` *(PK)*
- `player_match_fbref`
- `player_match_stats`
- `player_positions` *(PK)*
- `player_positions_v103` *(PK)*
- `player_season_stats` *(PK)*
- `scenario_teams`
- `team_match_fbref` *(PK)*
- `team_match_predictions_b12` *(PK)*
- `team_match_stats` *(PK)*
- `team_season_strength_v103` *(PK)*

### `league` (10 tables)

- `ea_fc26_player`
- `fixtures`
- `games`
- `league_averages_v103`
- `player_match_fbref`
- `player_match_stats`
- `player_season_stats`
- `team_match_fbref`
- `team_match_stats`
- `team_season_strength_v103`

### `player_id` (8 tables)

- `best_xi`
- `fixture_lineups`
- `player_match_fbref` *(PK)*
- `player_match_stats` *(PK)*
- `player_positions` *(PK)*
- `player_positions_v103` *(PK)*
- `player_season_stats` *(PK)*
- `players` *(PK)*

### `position_class` (7 tables)

- `best_xi`
- `ea_fc26_player`
- `player_positions` *(PK)*
- `player_positions_v103`
- `player_season_stats`
- `positions`
- `wc2026_squad`

### `game_id` (6 tables)

- `games` *(PK)*
- `player_match_fbref` *(PK)*
- `player_match_stats` *(PK)*
- `team_match_fbref` *(PK)*
- `team_match_predictions_b12` *(PK)*
- `team_match_stats` *(PK)*

### `model_version` (6 tables)

- `md38_evaluation_b12_b2` *(PK)*
- `md38_predictions_b12` *(PK)*
- `md38_score_grid_b12` *(PK)*
- `model_parameters_v103` *(PK)*
- `predictions`
- `team_match_predictions_b12` *(PK)*

### `fixture_id` (5 tables)

- `fixtures` *(PK)*
- `lineup_scenarios`
- `md38_evaluation_b12_b2` *(PK)*
- `md38_predictions_b12` *(PK)*
- `md38_score_grid_b12` *(PK)*

### `formation` (5 tables)

- `best_xi` *(PK)*
- `formation_slots` *(PK)*
- `formations` *(PK)*
- `scenario_teams`
- `team_match_fbref`

### `goals` (5 tables)

- `player_match_fbref`
- `player_match_stats`
- `player_season_stats`
- `team_match_fbref`
- `team_match_stats`

### `side` (5 tables)

- `fixture_lineups` *(PK)*
- `scenario_teams` *(PK)*
- `team_match_fbref`
- `team_match_predictions_b12`
- `team_match_stats`

### `created_at` (4 tables)

- `league_averages_v103`
- `lineup_scenarios`
- `team_match_predictions_b12`
- `team_season_strength_v103`

### `minutes` (4 tables)

- `best_xi`
- `player_match_fbref`
- `player_match_stats`
- `player_season_stats`

### `position` (4 tables)

- `ea_fc26_player`
- `player_match_fbref`
- `player_match_stats`
- `player_season_stats`

### `scenario_id` (4 tables)

- `fixture_lineups` *(PK)*
- `lineup_scenarios` *(PK)*
- `predictions`
- `scenario_teams` *(PK)*

### `assists` (3 tables)

- `player_match_fbref`
- `player_match_stats`
- `player_season_stats`

### `away_team` (3 tables)

- `fixtures`
- `games`
- `md38_predictions_b12`

### `club` (3 tables)

- `club_elo` *(PK)*
- `ea_fc26_player`
- `wc2026_squad`

### `ea_id` (3 tables)

- `ea_fc26_player` *(PK)*
- `ea_fc26_playstyle` *(PK)*
- `wc2026_squad`

### `home_team` (3 tables)

- `fixtures`
- `games`
- `md38_predictions_b12`

### `opponent` (3 tables)

- `team_match_fbref`
- `team_match_predictions_b12`
- `team_match_stats`

### `p_away_win` (3 tables)

- `md38_evaluation_b12_b2`
- `md38_predictions_b12`
- `predictions`

### `p_draw` (3 tables)

- `md38_evaluation_b12_b2`
- `md38_predictions_b12`
- `predictions`

### `p_home_win` (3 tables)

- `md38_evaluation_b12_b2`
- `md38_predictions_b12`
- `predictions`

### `position_code` (3 tables)

- `formation_slots`
- `player_positions_v103` *(PK)*
- `positions` *(PK)*

### `slot_no` (3 tables)

- `best_xi` *(PK)*
- `fixture_lineups` *(PK)*
- `formation_slots` *(PK)*

### `source` (3 tables)

- `ea_fc26_player`
- `games`
- `wc2026_squad`

### `away_goals` (2 tables)

- `games`
- `md38_score_grid_b12` *(PK)*

### `effective_position` (2 tables)

- `player_match_fbref`
- `player_match_stats`

### `home_goals` (2 tables)

- `games`
- `md38_score_grid_b12` *(PK)*

### `ingested_at` (2 tables)

- `ea_fc26_player`
- `wc2026_squad`

### `interceptions` (2 tables)

- `ea_fc26_player`
- `player_match_fbref`

### `match_date` (2 tables)

- `fixtures`
- `games`

### `n_matches` (2 tables)

- `player_positions_v103`
- `team_season_strength_v103`

### `name_norm` (2 tables)

- `ea_fc26_player`
- `wc2026_squad`

### `nation_code` (2 tables)

- `ea_fc26_player`
- `wc2026_squad`

### `nation_name` (2 tables)

- `ea_fc26_player`
- `wc2026_squad`

### `np_xg` (2 tables)

- `player_season_stats`
- `team_match_stats`

### `opponent_goals` (2 tables)

- `team_match_fbref`
- `team_match_stats`

### `own_goals` (2 tables)

- `player_match_fbref`
- `player_match_stats`

### `player_name` (2 tables)

- `players`
- `wc2026_squad`

### `position_id` (2 tables)

- `player_match_fbref`
- `player_match_stats`

### `priority` (2 tables)

- `player_positions`
- `player_positions_v103`

### `red_cards` (2 tables)

- `player_match_fbref`
- `player_match_stats`

### `shots` (2 tables)

- `player_match_fbref`
- `player_match_stats`

### `source_url` (2 tables)

- `ea_fc26_player`
- `wc2026_squad`

### `xa` (2 tables)

- `player_match_stats`
- `player_season_stats`

### `xg` (2 tables)

- `player_match_stats`
- `team_match_stats`

### `xg_away` (2 tables)

- `md38_predictions_b12`
- `predictions`

### `xg_home` (2 tables)

- `md38_predictions_b12`
- `predictions`

### `yellow_cards` (2 tables)

- `player_match_fbref`
- `player_match_stats`
