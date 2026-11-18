import math

import pandas as pd
import pytest

from src.analysis import hit_features as hf
from src.names import norm_name


def oldest_first(df):
    return df.iloc[::-1].reset_index(drop=True)


SNAP = {
    "padv": pd.DataFrame({"USG_PCT": [0.3], "TS_PCT": [0.6], "REB_PCT": [0.1], "AST_PCT": [0.2]}, index=[7]),
    "drive": pd.DataFrame({"DRIVES": [12.0]}, index=[7]),
    "poss": pd.DataFrame({"PTS_PER_TOUCH": [0.4]}, index=[7]),
    "reb": pd.DataFrame({"REB_CHANCES": [10.0, 6.0], "REB_CHANCE_PCT": [0.6, 0.5], "REB_CONTEST_PCT": [0.3, 0.3]}, index=[7, 8]),
    "pass": pd.DataFrame({"POTENTIAL_AST": [8.0, 4.0], "AST": [5.0, 2.0], "PASSES_MADE": [50.0, 30.0], "AST_TO_PASS_PCT": [0.1, 0.07]}, index=[7, 8]),
    "cs": pd.DataFrame({"CATCH_SHOOT_FG3A": [4.0]}, index=[7]),
    "pu": pd.DataFrame({"PULL_UP_FG3A": [1.0]}, index=[7]),
    "tadv": pd.DataFrame({"PACE": [100.0, 104.0], "DEF_RATING": [110.0, 116.0], "OREB_PCT": [0.25, 0.3]}, index=["BOS", "NYK"]),
    "tbase": pd.DataFrame({"FGA": [88.0, 90.0], "FGM": [41.0, 40.0], "FG_PCT": [0.47, 0.44]}, index=["BOS", "NYK"]),
    "topp": pd.DataFrame({"OPP_PTS": [110.0, 120.0], "OPP_REB": [44.0, 46.0], "OPP_AST": [25.0, 28.0], "OPP_FG3A": [35.0, 40.0]}, index=["BOS", "NYK"]),
    "ocs": pd.DataFrame({"FG3A": [20.0, 25.0]}, index=["BOS", "NYK"]),
    "opu": pd.DataFrame({"FG3A": [10.0, 12.0]}, index=["BOS", "NYK"]),
}
CTX = {"player_id": 7, "team": "BOS", "opp": "NYK", "is_home": True, "rest_days": 1,
       "teammates_out_min": 20.0, "opp_out_min": 0.0,
       "role_absorption": {"PTS": 3.0, "REB": 1.0, "AST": 0.5, "MIN": 4.0}}


@pytest.mark.parametrize("stat", ["PTS", "REB", "AST", "FG3M", "PRA", "PR", "PA", "RA"])
def test_every_market_builds_finite_features(make_log, stat):
    f = hf.build_features(stat, 10.5, 0.5, oldest_first(make_log(n=12)), SNAP, CTX)
    assert f and all(math.isfinite(v) for v in f.values())
    assert f["b2b"] == 1.0 and f["home"] == 1.0 and f["teammates_out"] == 2.0


def test_market_specific_features(make_log):
    log = oldest_first(make_log(n=12))
    assert "usg" in hf.build_features("PTS", 20.5, 0.5, log, SNAP, CTX)
    assert "reb_chances" in hf.build_features("REB", 6.5, 0.5, log, SNAP, CTX)
    assert "potential_ast" in hf.build_features("AST", 4.5, 0.5, log, SNAP, CTX)
    f3 = hf.build_features("FG3M", 2.5, 0.5, log, SNAP, CTX)
    assert f3["cs_share"] == 0.8 and f3["opp_mix_idx"] > 1.0
    assert "usg" not in f3


def test_form_features_track_the_line(make_log):
    log = oldest_first(make_log([30] * 12))
    hot = hf.build_features("PTS", 20.5, 0.5, log, SNAP, CTX)
    cold = hf.build_features("PTS", 40.5, 0.5, log, SNAP, CTX)
    assert hot["z_season"] > 0 > cold["z_season"] and hot["hit_season"] == 1.0
    assert hot["role_boost"] > 0 and hot["role_minutes"] > 0


def test_too_few_games_and_partial(make_log):
    log = oldest_first(make_log(n=3))
    assert hf.build_features("PTS", 20.5, 0.6, log, SNAP, CTX) is None
    partial = hf.build_features("PTS", 20.5, 0.6, log, SNAP, CTX, allow_partial=True)
    assert set(partial) == {"mkt_logit", "line_log"}
    assert hf.build_features("BLK", 1.5, 0.5, log, SNAP, CTX) is None


def test_missing_snapshot_is_neutral(make_log):
    f = hf.build_features("PRA", 30.5, 0.5, oldest_first(make_log(n=10)), {}, {"player_id": 7})
    assert f["pace_idx"] == 1.0 and f["opp_def_idx"] == 1.0


def team_log(rows):
    """rows: (game_id, date, player_id, name, minutes) — one row per player-game."""
    df = pd.DataFrame(rows, columns=["GAME_ID", "GAME_DATE", "PLAYER_ID", "PLAYER_NAME", "MIN"])
    for c in ("PTS", "REB", "AST", "FG3A", "FG3M", "FGA"):
        df[c] = 0.0
    return df


def season(players, games=10, missing=None):
    """Every player plays every game except (game_index, player_id) pairs in `missing`."""
    rows = []
    for g in range(games):
        for pid, name, mins in players:
            if (g, pid) not in (missing or set()):
                rows.append((f"G{g}", f"2026-01-{g + 1:02d}", pid, name, mins))
    return team_log(rows)


def test_team_absences_vs_usual():
    players = [(1, "Star One", 34.0), (2, "Role Two", 20.0), (3, "Bench Three", 8.0)]
    log = season(players, games=11, missing={(10, 1)})          # star sits game 11
    assert hf.team_absences(log, "2026-01-11", tonight_game_id="G10") == pytest.approx(34.0)
    assert hf.team_absences(log, "2026-01-11", tonight_out={"star one"}, norm=norm_name) == pytest.approx(34.0)
    assert hf.team_absences(log, "2026-01-11", tonight_out=set()) == 0.0
    assert hf.team_absences(log, "2026-01-01") == 0.0          # nothing before


def test_role_absorption_goes_to_similar_players():
    log = season([(1, "Guard A", 30.0), (2, "Guard B", 30.0), (3, "Center C", 30.0)], games=11)
    log.loc[log.PLAYER_ID.isin([1, 2]), ["AST", "FG3A", "FGA"]] = [8.0, 8.0, 15.0]
    log.loc[log.PLAYER_ID == 3, ["REB", "FGA"]] = [12.0, 10.0]
    out = hf.role_absorption(log, "2026-01-11", tonight_out={"guard a"}, norm=norm_name)
    assert out[2]["MIN"] > out[3]["MIN"]                       # the other guard absorbs the minutes
    assert out[2]["AST"] > out[3]["AST"]
    assert hf.role_absorption(log.iloc[0:0], "2026-01-11") == {}
