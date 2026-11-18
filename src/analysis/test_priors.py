import pandas as pd
import pytest

import config
from src.analysis import priors


@pytest.fixture(autouse=True)
def _reset_memo(monkeypatch):
    monkeypatch.setattr(priors, "_tables", {})
    monkeypatch.setattr(priors, "_failed_at", {})


TOTALS = pd.DataFrame([
    {"PLAYER_ID": 1, "GP": 70, "MIN": 2100.0, "PTS": 1400, "REB": 420, "AST": 280, "FG3M": 140},
    {"PLAYER_ID": 2, "GP": 4, "MIN": 40.0, "PTS": 10, "REB": 5, "AST": 2, "FG3M": 1},     # too few games
])


def test_build_prior_rates():
    p = priors.build_prior(TOTALS.iloc[0].to_dict())
    assert p["GP"] == 70 and p["MPG"] == 30
    assert p["rates"]["PTS"] == pytest.approx(1400 / 2100)
    assert p["rates"]["PRA"] == pytest.approx((1400 + 420 + 280) / 2100)
    assert priors.build_prior(TOTALS.iloc[1].to_dict()) is None
    assert priors.build_prior({"GP": 50, "MIN": 0}) is None


def test_get_player_prior_uses_previous_season(monkeypatch):
    seen = []
    monkeypatch.setattr(priors, "get_league_player_totals", lambda s: seen.append(s) or TOTALS)
    assert priors.get_player_prior(1, season="2026-27")["GP"] == 70
    assert priors.get_player_prior(2, season="2026-27") is None
    assert priors.get_player_prior(1, season="2026-27")["GP"] == 70
    assert seen == ["2025-26"]          # fetched once, memoised


def test_get_player_prior_backs_off_after_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(priors, "get_league_player_totals", lambda s: calls.append(s) or pd.DataFrame())
    assert priors.get_player_prior(1) is None
    assert priors.get_player_prior(1) is None
    assert len(calls) == 1


def test_prior_weight_fades_with_games():
    prior = {"GP": 70}
    assert priors.prior_weight(0, prior) == config.PLAYER_PRIOR_GAMES
    assert priors.prior_weight(config.PLAYER_PRIOR_FADE_GAMES, prior) == 0
    assert priors.prior_weight(5, None) == 0
    half = priors.prior_weight(0, {"GP": config.PLAYER_PRIOR_FULL_GP // 2})
    assert half == pytest.approx(config.PLAYER_PRIOR_GAMES / 2)


def test_prior_mean(make_log):
    prior = priors.build_prior(TOTALS.iloc[0].to_dict())
    assert priors.prior_mean(prior, "PTS", make_log(n=5, minutes=30)) == pytest.approx(20.0)
    assert priors.prior_mean(prior, "XYZ", make_log(n=5)) is None
    assert priors.prior_mean(prior, "PTS", pd.DataFrame()) is None


def test_probabilities_are_sensible():
    assert priors.prob_hit(28, "PTS", 22.5, "over") > 0.65
    over, under = priors.prob_hit(10, "REB", 9.5, "over"), priors.prob_hit(10, "REB", 9.5, "under")
    assert over + under == pytest.approx(1.0)
    assert priors.prob_hit(10, "REB", 10.0, "under") < priors.prob_hit(10, "REB", 10.5, "under")
    assert priors.prob_hit(0, "PTS", 0.5, "over") == 0.0
    assert priors.prob_hit(0, "PTS", 0.5, "under") == 1.0


def test_quantile_and_dispersion():
    lo, hi = priors.quantile(20, "PTS", 0.1), priors.quantile(20, "PTS", 0.9)
    assert lo < 20 < hi
    assert priors.quantile(0, "PTS", 0.5) == 0
    assert priors._dispersion(0.1, "FG3M") > 0
    assert priors._cdf(-1, 5, 10) == 0.0
    assert priors._cdf(3, 0, 10) == 1.0


def test_implied_mean_inverts_prob_hit():
    mu = priors.implied_mean("FG3M", 3.5, 0.40)
    assert priors.prob_hit(mu, "FG3M", 3.5, "over") == pytest.approx(0.40, abs=0.005)
