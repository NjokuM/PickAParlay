from src import models
from testkit import make_prop, make_vp


def test_dataclasses_hold_their_fields():
    p = make_prop(line=5.5)
    assert p.line == 5.5 and p.game.home_team == "BOS" and p.is_paddy_power is True and p.is_alternate is False
    vp = make_vp(score=72)
    assert vp.value_score == 72 and vp.suspicious_line is False
    leg = models.BetLeg(valued_prop=vp, side="over", decimal_odds=1.9)
    slip = models.BetSlip(legs=[leg], combined_decimal_odds=1.9, target_decimal_odds=None, total_value_score=72, summary="x")
    assert slip.has_correlated_legs is False
    assert models.InjuryReport("A", "BOS", "out").status == "out"
    assert models.FactorResult("f", 50, 0.1, [], {}).confidence == 1.0
    mm = models.MarketMapping(market="player_points", stat_key="PTS", compute="PTS")
    assert mm.stat_key == "PTS"
