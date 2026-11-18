import pandas as pd

from src.analysis.factors import season_avg


def test_avg_above_line_favours_over(make_log):
    r = season_avg.compute(make_log([25] * 12), "PTS", 20.5)
    assert r.score > 50 and r.confidence == 1.0
    assert season_avg.compute(make_log([25] * 12), "PTS", 20.5, side="under").score < 50


def test_under_when_avg_below(make_log):
    assert season_avg.compute(make_log([15] * 12), "PTS", 20.5, side="under").score > 50
    assert season_avg.compute(make_log([15] * 12), "PTS", 20.5).score < 50


def test_role_change_uses_recent_window(make_log):
    df = make_log([30] * 20 + [10] * 20)        # recent 20 games much higher
    r = season_avg.compute(df, "PTS", 20.5)
    assert r.data["role_changed"] and r.data["primary_avg"] == 30


def test_prior_blend_and_confidence(make_log):
    r = season_avg.compute(make_log([30] * 4), "PTS", 20.5, prior_mu=20.0, prior_k=6)
    assert 20 < r.data["primary_avg"] < 30 and r.confidence == 1.0
    low = season_avg.compute(make_log([30] * 4), "PTS", 20.5)
    assert low.confidence == 0.4 and any("Low confidence" in e for e in low.evidence)


def test_playoff_weighting_and_edge_cases(make_log):
    df = make_log([10, 30, 30, 30, 30]).assign(PLAYOFF_WEIGHT=[1.35, 1, 1, 1, 1], IS_PLAYOFF_GAME=[True] + [False] * 4)
    assert any("playoff" in e for e in season_avg.compute(df, "PTS", 20.5).evidence)
    assert season_avg.compute(pd.DataFrame(), "PTS", 20).confidence == 0
    assert season_avg.compute(make_log([5] * 3), "PTS", 0).score == 50
