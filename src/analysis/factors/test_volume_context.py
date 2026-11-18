import pandas as pd

from src.analysis.factors import volume_context


def test_points_market_uses_fga(make_log):
    r = volume_context.compute(make_log(n=10, minutes=34, FGA=20.0), "PTS", 25.5, "player_points")
    assert r.data["usage_score"] > 90 and any("FGA" in e for e in r.evidence)


def test_threes_and_assists_markets(make_log):
    t = volume_context.compute(make_log(n=10, FG3A=9.0), "FG3M", 2.5, "player_threes")
    assert any("3PA" in e for e in t.evidence)
    a = volume_context.compute(make_log(n=10, AST=8.0), "AST", 6.5, "player_assists")
    assert any("AST per 36" in e for e in a.evidence)
    zero = volume_context.compute(make_log(n=10, minutes=0.0), "AST", 6.5, "player_assists")
    assert any("unavailable" in e for e in zero.evidence)


def test_declining_minutes_injury_boost_and_under(make_log):
    df = make_log(n=10).assign(MIN=[20] * 5 + [34] * 5)
    r = volume_context.compute(df, "REB", 6.5, "player_rebounds", teammate_minutes_lost=60)
    assert any("declining" in e for e in r.evidence) and r.data["injury_minutes_boost"] > 0
    under = volume_context.compute(df, "REB", 6.5, "player_rebounds", side="under")
    assert under.score == round(100 - volume_context.compute(df, "REB", 6.5, "player_rebounds").score, 1)


def test_no_data():
    assert volume_context.compute(pd.DataFrame(), "PTS", 1, "player_points").confidence == 0
