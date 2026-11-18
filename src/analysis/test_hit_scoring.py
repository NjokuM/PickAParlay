import pytest

import config
from src.analysis import hit_scoring
from src.models import InjuryReport


def oldest_first(df):
    return df.iloc[::-1].reset_index(drop=True)


def test_score_scale():
    assert hit_scoring.score_from_probability(0.5) == 50.0
    assert 69 < hit_scoring.score_from_probability(0.58) < 71
    assert hit_scoring.score_from_probability(0.9) < 100
    assert hit_scoring.score_from_probability(0.1) > 0


def test_score_returns_chance_edge_and_factor(offline_grading, prop_factory):
    log = oldest_first(offline_grading["log"])
    r = hit_scoring.score(prop_factory(over=1.6, under=2.4), "over", log, "PTS", "player_points", "BOS", "NYK", True, [], "2026-27")
    assert 0 < r["p_side"] < 1 and r["p_market"] == pytest.approx((1 / 1.6) / (1 / 1.6 + 1 / 2.4))
    assert r["edge"] == pytest.approx(r["p_side"] - r["p_market"])
    assert r["factor"].name == "Hit Model" and r["factor"].weight == 0.0
    assert r["factor"].evidence[0].startswith("Chance of hitting")
    under = hit_scoring.score(prop_factory(over=1.6, under=2.4), "under", log, "PTS", "player_points", "BOS", "NYK", True, [], "2026-27")
    assert under["p_side"] == pytest.approx(1 - r["p_side"])


def test_early_season_phase_in_and_no_special(offline_grading, prop_factory):
    log = oldest_first(offline_grading["log"].head(4))          # 4 games
    r = hit_scoring.score(prop_factory(), "over", log, "PTS", "player_points", "BOS", "NYK", True, [], "2026-27")
    assert r["factor"].data["stats_weight"] == pytest.approx((4 - 3) / 9, abs=1e-3)   # stored rounded
    assert r["is_special"] is False and any("Early season" in e for e in r["factor"].evidence)


def test_injuries_feed_the_context(offline_grading, prop_factory):
    inj = [InjuryReport("A B", "BOS", "out")]
    r = hit_scoring.score(prop_factory(), "over", oldest_first(offline_grading["log"]), "PTS", "player_points", "BOS", "NYK", True, inj, "2026-27")
    assert r is not None


def test_no_prices_means_no_score(offline_grading, prop_factory):
    assert hit_scoring.score(prop_factory(over=0, under=0), "over", offline_grading["log"], "PTS", "player_points", "BOS", "NYK", True, [], "2026-27") is None


def test_absence_helpers_without_league_log():
    assert hit_scoring._absences("BOS", "2026-04-01", set(), None) == 0.0
    assert hit_scoring._role("BOS", "2026-04-01", set(), None) == {}
