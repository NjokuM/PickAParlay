import pandas as pd

from src.analysis.factors import consistency


def test_over_hits_every_game(make_log):
    r = consistency.compute(make_log([25, 24, 26, 30, 22]), "PTS", 20.5)
    assert r.data["hits"] == 5 and r.data["floor"] == 22
    assert r.score > 80 and r.confidence == 0.5        # 5 games of the 10 needed


def test_under_side_mirrors(make_log):
    over = consistency.compute(make_log([10] * 10), "PTS", 20.5, side="over")
    under = consistency.compute(make_log([10] * 10), "PTS", 20.5, side="under")
    assert under.score > over.score and under.data["ceiling"] == 10
    assert any("stayed below" in e for e in under.evidence)


def test_prior_blends_components(make_log):
    plain = consistency.compute(make_log([30] * 4), "PTS", 20.5)
    blended = consistency.compute(make_log([30] * 4), "PTS", 20.5, prior_mu=15.0, prior_k=8.0)
    assert blended.data["prior_share"] == round(8 / 12, 3)
    assert blended.data["mean"] < plain.data["mean"] and blended.score < plain.score
    assert blended.confidence == 0.8            # capped by 4 of the 5 effective games needed
    assert any("last-season prior" in e for e in blended.evidence)


def test_no_data():
    assert consistency.compute(pd.DataFrame(), "PTS", 10).confidence == 0
    assert consistency.compute(pd.DataFrame({"PTS": [1.0]}).assign(CTX_WEIGHT=0.0), "PTS", 10).confidence == 0


def test_playoff_weight_and_zero_line(make_log):
    df = make_log([10, 20]).assign(PLAYOFF_WEIGHT=[1.35, 1.0], IS_PLAYOFF_GAME=[True, False])
    r = consistency.compute(df, "PTS", 15.5)
    assert any("playoff" in e for e in r.evidence)
    assert consistency._bound_contrib(5, 0, "over") == 0.0 and consistency._mean_contrib(5, 0, "over") == 0.5
    assert consistency._bound_contrib(30, 20, "under") == 0.5
