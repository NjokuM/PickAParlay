import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(__file__))

TEAMS = ["BOS", "NYK", "MIA", "CHI"]


@pytest.fixture
def season_log():
    """A small LeagueGameLog-style season: 4 teams, 3 players each, 24 game dates."""
    rng = np.random.default_rng(0)
    rows, gid = [], 0
    dates = pd.date_range("2026-01-01", periods=24, freq="2D")
    for d in dates:
        for home, away in (("BOS", "NYK"), ("MIA", "CHI")):
            gid += 1
            for team, opp, sep in ((home, away, " vs. "), (away, home, " @ ")):
                for k in range(3):
                    pid = TEAMS.index(team) * 10 + k
                    if pid == 0 and gid % 5 == 0:
                        continue                     # player 0 sits sometimes → absences
                    pts = float(rng.poisson(20 - 4 * k))
                    rows.append({"PLAYER_ID": pid, "PLAYER_NAME": f"Player {pid}", "TEAM_ABBREVIATION": team,
                                 "GAME_ID": f"G{gid}", "GAME_DATE": d.strftime("%Y-%m-%d"), "MATCHUP": f"{team}{sep}{opp}",
                                 "MIN": 30.0 - 5 * k, "PTS": pts, "REB": float(rng.poisson(6)), "AST": float(rng.poisson(4)),
                                 "FG3M": float(rng.poisson(2)), "FG3A": float(rng.poisson(5)) + 1, "FGA": 14.0, "FTA": 4.0})
    return pd.DataFrame(rows)


@pytest.fixture
def graded_props_file(tmp_path, season_log):
    """Graded prop rows (prod_results format) for players 0 and 10 on the later dates."""
    out, rng = [], np.random.default_rng(1)
    for d in sorted(season_log.GAME_DATE.unique())[12:]:
        for pid in (0, 10, 20):
            g = season_log[(season_log.PLAYER_ID == pid) & (season_log.GAME_DATE == d)]
            if g.empty:
                continue
            for market, line in (("player_points", 18.5), ("player_rebounds", 5.5), ("player_threes", 1.5)):
                actual = {"player_points": g.PTS, "player_rebounds": g.REB, "player_threes": g.FG3M}[market].iloc[0]
                for side in ("over", "under"):
                    hit = (actual > line) if side == "over" else (actual < line)
                    out.append({"nba_player_id": pid, "player_name": f"Player {pid}", "game_date": d, "market": market,
                                "line": line, "side": side, "over_odds": float(rng.uniform(1.7, 2.1)), "under_odds": 1.9,
                                "leg_result": "HIT" if hit else "MISS", "value_score": 60.0, "is_alternate": 0})
    path = tmp_path / "graded.json"
    path.write_text(json.dumps(out))
    return path


@pytest.fixture
def fake_snapshot():
    """Tables shaped like src/api/league_tables.TABLES output (indexed)."""
    teams = pd.DataFrame({"PACE": [100.0] * 4, "DEF_RATING": [112.0] * 4, "OREB_PCT": [0.25] * 4, "FGA": [88.0] * 4,
                          "FGM": [41.0] * 4, "FG_PCT": [0.46] * 4, "OPP_PTS": [112.0] * 4, "OPP_REB": [44.0] * 4,
                          "OPP_AST": [25.0] * 4, "OPP_FG3A": [36.0] * 4, "FG3A": [24.0] * 4}, index=TEAMS)
    players = pd.DataFrame({"USG_PCT": 0.2, "TS_PCT": 0.57, "REB_PCT": 0.1, "AST_PCT": 0.15, "DRIVES": 8.0, "PTS_PER_TOUCH": 0.3,
                            "REB_CHANCES": 9.0, "REB_CHANCE_PCT": 0.6, "REB_CONTEST_PCT": 0.3, "POTENTIAL_AST": 7.0, "AST": 4.0,
                            "PASSES_MADE": 40.0, "AST_TO_PASS_PCT": 0.1, "CATCH_SHOOT_FG3A": 3.0, "PULL_UP_FG3A": 2.0},
                           index=[t * 10 + k for t in range(4) for k in range(3)])
    return {k: teams for k in ("tbase", "tadv", "topp", "ocs", "opu")} | {k: players for k in ("cs", "pu", "reb", "pass", "drive", "poss", "padv")}
