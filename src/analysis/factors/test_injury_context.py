import pytest

from src.analysis.factors import injury_context as ic
from src.models import InjuryReport

USAGE = {"star guard": {"mpg": 34.0, "fga": 20.0}, "bench big": {"mpg": 12.0, "fga": 3.0}}


@pytest.fixture(autouse=True)
def usage(monkeypatch):
    monkeypatch.setattr(ic, "get_league_player_usage", lambda: USAGE)


def test_player_out_means_avoid():
    r = ic.compute("Jane Doe", "BOS", "NYK", "player_points", [InjuryReport("Jane Doe", "BOS", "out")])
    assert r.score == 0 and ic.should_avoid(r)


def test_questionable_player_side_dependent():
    reports = [InjuryReport("Jane Doe", "BOS", "questionable")]
    assert ic.compute("Jane Doe", "BOS", "NYK", "player_points", reports, side="under").score > \
        ic.compute("Jane Doe", "BOS", "NYK", "player_points", reports, side="over").score


def test_star_teammate_out_boosts_points_over():
    reports = [InjuryReport("Star Guard", "BOS", "out")]
    over = ic.compute("Jane Doe", "BOS", "NYK", "player_points", reports)
    assert over.score > 75 and over.data["depth_minutes_lost"] == 34
    assert any("Teammate out" in e for e in over.evidence)
    assert ic.compute("Jane Doe", "BOS", "NYK", "player_assists", reports).score < over.score


def test_many_teammates_and_opponents_out():
    reports = [InjuryReport(f"Guy {i}", "BOS", "out") for i in range(5)] + \
              [InjuryReport("Star Guard", "NYK", "out"), InjuryReport("Bench Big", "NYK", "doubtful")]
    r = ic.compute("Jane Doe", "BOS", "NYK", "player_points", reports)
    assert any("teammates out" in e for e in r.evidence)
    u = ic.compute("Jane Doe", "BOS", "NYK", "player_points", reports, side="under")
    assert u.score < r.score


def test_helpers():
    assert ic._lookup_player_mpg("star guard", USAGE) == (34.0, True)
    assert ic._lookup_player_mpg("Someone Big", USAGE)[0] == 12.0      # surname fallback
    assert ic._lookup_player_mpg("Nobody Here", USAGE) == (ic._DEFAULT_MPG, False)
    assert ic._depth_depletion_impact(0) == 0
    assert ic._depth_depletion_impact(10) < ic._depth_depletion_impact(40) < ic._depth_depletion_impact(70) < ic._depth_depletion_impact(200) <= 30
