import pandas as pd

from src.analysis.factors import home_away


def test_home_games_only(make_log):
    df = make_log([30, 10] * 5)                 # home games (even rows) score 30, away 10
    home = home_away.compute(df, "PTS", 20.5, tonight_is_home=True)
    away = home_away.compute(df, "PTS", 20.5, tonight_is_home=False)
    assert home.data["avg"] == 30 and away.data["avg"] == 10
    assert home.score > away.score and home.name == "Home Performance"


def test_under_and_low_confidence(make_log):
    r = home_away.compute(make_log([10, 10, 10, 10]), "PTS", 20.5, True, side="under")
    assert r.score > 50 and r.confidence < 1 and any("Low confidence" in e for e in r.evidence)


def test_no_data(make_log):
    assert home_away.compute(pd.DataFrame(), "PTS", 10, True).confidence == 0
    only_home = make_log([10], home_pattern=[True])
    assert home_away.compute(only_home, "PTS", 10, tonight_is_home=False).confidence == 0
