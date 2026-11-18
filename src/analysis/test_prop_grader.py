import pandas as pd
import pytest

import config
from src.analysis import prop_grader
from src.models import InjuryReport


def test_grades_with_v2_factors_and_shadow_hit_model(offline_grading, prop_factory, monkeypatch):
    monkeypatch.setattr(config, "SCORE_SOURCE", "factors")
    vp = prop_grader.grade_prop(prop_factory(), [], side="over")
    names = [f.name for f in vp.factors]
    assert "Consistency" in names and "Hit Model" not in names
    assert vp.value_score == pytest.approx(prop_grader.compute_value_score(vp.factors), abs=0.1)
    bd = vp.backing_data
    assert bd["side"] == "over" and bd["hit_probability"] is not None    # shadow model still stored
    assert bd["is_special"] is False and bd["opponent"] == "NYK" and bd["tonight_home"] is True


def test_hit_model_source_sets_the_score(offline_grading, prop_factory, monkeypatch):
    monkeypatch.setattr(config, "SCORE_SOURCE", "hit_model")
    vp = prop_grader.grade_prop(prop_factory(), [], side="under")
    assert vp.factors[-1].name == "Hit Model"
    from src.analysis.hit_scoring import score_from_probability
    assert vp.value_score == score_from_probability(vp.backing_data["hit_probability"])


@pytest.mark.parametrize("market", ["player_rebounds", "player_assists", "player_threes",
                                    "player_points_rebounds_assists", "player_points_alternate"])
def test_every_market_grades(offline_grading, prop_factory, market):
    assert prop_grader.grade_prop(prop_factory(market=market, line=5.5), []) is not None


def test_injured_player_and_unknown_market(offline_grading, prop_factory):
    assert prop_grader.grade_prop(prop_factory(), [InjuryReport("Jane Doe", "BOS", "out")]) is None
    assert prop_grader.grade_prop(prop_factory(market="player_blocks"), []) is None


def test_no_games_this_season(offline_grading, prop_factory):
    offline_grading["log"] = pd.DataFrame()
    assert prop_grader.grade_prop(prop_factory(), []) is None


def test_one_game_still_graded(offline_grading, prop_factory):
    offline_grading["log"] = offline_grading["log"].head(1)
    assert prop_grader.grade_prop(prop_factory(), []) is not None


def test_returning_from_injury_adjusts(offline_grading, prop_factory, make_log):
    log = make_log([10, 12] + [25] * 10, minutes=30)
    log.loc[:1, "MIN"] = 15
    log.loc[2:, "GAME_DATE"] = log.loc[2:, "GAME_DATE"] - pd.Timedelta(days=20)
    offline_grading["log"] = log
    over = prop_grader.grade_prop(prop_factory(), [], side="over")
    assert over.backing_data["returning_from_injury"] is True
    assert prop_grader.grade_prop(prop_factory(), [], side="under") is not None


def test_player_team_resolution(prop_factory, monkeypatch, make_log):
    prop = prop_factory(home="BOS", away="NYK")
    monkeypatch.setattr(prop_grader, "get_player_current_team", lambda pid: "NYK")
    assert prop_grader._get_player_team(prop, prop.game) == "NYK"
    monkeypatch.setattr(prop_grader, "get_player_current_team", lambda pid: "LAL")      # traded elsewhere
    assert prop_grader._get_player_team(prop, prop.game, make_log(n=3, team="NYK", opp="MIA")) == "NYK"
    monkeypatch.setattr(prop_grader, "get_player_current_team", lambda pid: None)
    assert prop_grader._get_player_team(prop, prop.game, make_log(n=3, team="MIA", opp="CHI")) == "BOS"
    monkeypatch.setattr(prop_grader, "get_player_game_log", lambda pid: pd.DataFrame())
    assert prop_grader._get_player_team(prop, prop.game) == "BOS"


def test_favourite_and_line_value_helpers():
    assert prop_grader._team_is_favorite(None, True)
    assert prop_grader._team_is_favorite(-5, True) and not prop_grader._team_is_favorite(-5, False)
    assert prop_grader._team_is_favorite(5, False)
    assert prop_grader._compute_line_value(20, 20).score == 50
    assert prop_grader._compute_line_value(0, 20).score == 50
