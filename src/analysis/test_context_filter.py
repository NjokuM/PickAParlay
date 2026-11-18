import pandas as pd

import config
from src.analysis import context_filter as cf


def test_team_weights_downweight_previous_team(make_log):
    df = pd.concat([make_log(n=5, team="LAL"), make_log(n=5, team="BOS", start="2026-02-01")])
    out = cf.apply_context_weights(df, current_team_abbr="LAL", tonight_is_b2b=False)
    assert set(out.loc[out.MATCHUP.str.startswith("LAL"), "CTX_WEIGHT"]) == {config.CONTEXT_WEIGHTS["current_team"]}
    assert set(out.loc[out.MATCHUP.str.startswith("BOS"), "CTX_WEIGHT"]) == {config.CONTEXT_WEIGHTS["previous_team"]}


def test_previous_team_zeroed_once_enough_current_games(make_log):
    df = pd.concat([make_log(n=config.MIN_CURRENT_TEAM_GAMES, team="LAL"), make_log(n=3, team="BOS", start="2025-12-01")])
    out = cf.apply_context_weights(df, "LAL", False)
    assert set(out.loc[out.MATCHUP.str.startswith("BOS"), "CTX_WEIGHT"]) == {0.0}


def test_b2b_weights(make_log):
    df = make_log(n=4, every=1)          # consecutive days → B2B games
    out = cf.apply_context_weights(df, "BOS", tonight_is_b2b=True)
    assert out.IS_B2B_GAME.iloc[0] and not out.IS_B2B_GAME.iloc[-1]
    assert out.CTX_WEIGHT.iloc[-1] == config.CONTEXT_WEIGHTS["normal_rest_b2b"]


def test_empty_and_missing_matchup():
    assert cf.apply_context_weights(pd.DataFrame(), "BOS", False).empty
    out = cf._apply_team_weights(pd.DataFrame({"PTS": [1]}), "BOS", "2025-26")
    assert out.CTX_WEIGHT.tolist() == [1.0]
    assert cf._apply_b2b_weights(pd.DataFrame({"PTS": [1]})).equals(pd.DataFrame({"PTS": [1]}))


def test_home_away_weights(make_log):
    df = make_log(n=4).assign(CTX_WEIGHT=1.0)
    home = cf._apply_home_away_weights(df.copy(), tonight_is_home=True)
    assert (home.loc[home.MATCHUP.str.contains("@"), "CTX_WEIGHT"] == 0).all()
    away = cf._apply_home_away_weights(df.copy(), tonight_is_home=False)
    assert (away.loc[away.MATCHUP.str.contains("vs."), "CTX_WEIGHT"] == 0).all()
    assert cf._apply_home_away_weights(pd.DataFrame({"x": [1]}), True).equals(pd.DataFrame({"x": [1]}))


def test_filter_vs_opponent_and_season_recency(make_log):
    recent = make_log(n=2, opp="NYK")
    old = make_log(n=2, opp="NYK", start="2025-01-01")        # > 1 year earlier
    other = make_log(n=2, opp="MIA")
    h2h = cf.filter_vs_opponent(pd.concat([recent, old, other]), "NYK", "BOS")
    assert len(h2h) == 4
    weights = sorted(h2h.CTX_WEIGHT.unique())
    assert weights[-1] == 1.0 and weights[0] < 1.0
    assert cf.filter_vs_opponent(pd.DataFrame(), "NYK", "BOS").empty
    assert cf.filter_vs_opponent(make_log(n=2, opp="MIA"), "NYK", "BOS").empty


def test_filter_vs_opponent_previous_team_rows(make_log):
    df = pd.concat([make_log(n=2, team="BOS", opp="NYK"), make_log(n=2, team="LAL", opp="NYK", start="2026-02-01")])
    h2h = cf.filter_vs_opponent(df, "NYK", "BOS")
    assert h2h.loc[h2h.MATCHUP.str.startswith("LAL"), "CTX_WEIGHT"].max() < 0.1


def test_confidence_helpers(make_log):
    assert cf.compute_confidence(5, 10) == 0.5
    assert cf.compute_confidence(20, 10) == 1.0
    assert cf.effective_sample_size(pd.DataFrame()) == 0.0
    assert cf.effective_sample_size(make_log(n=3)) == 3.0
    assert cf.effective_sample_size(make_log(n=3).assign(CTX_WEIGHT=0.5)) == 1.5
    assert cf._team_from_matchup("BOS @ NYK") == "BOS"
    assert cf._team_from_matchup("BOSXYZ") == "BOS"
