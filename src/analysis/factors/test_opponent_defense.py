from src.analysis.factors import opponent_defense as od

PROFILE = {"TEAM_NAME": "Utah Jazz", "OPP_PTS": 120.0, "OPP_PTS_pct": 0.9, "OPP_REB": 46.0, "OPP_REB_pct": 0.5,
           "OPP_AST": 28.0, "OPP_AST_pct": 0.8, "OPP_FG3M": 15.0, "OPP_FG3M_pct": 0.95,
           "PACE": 102.0, "PACE_pct": 0.9, "DEF_RATING": 118.0, "GP": 40, "PRIOR_GAMES": 0.0}


def test_weak_defence_favours_over(monkeypatch):
    monkeypatch.setattr(od, "get_opponent_defensive_profile", lambda *a, **k: PROFILE)
    over = od.compute(1, "player_points", "over")
    under = od.compute(1, "player_points", "under")
    assert over.score > 80 > under.score and over.confidence == 1.0
    assert any("weak" in e for e in over.evidence)


def test_early_season_confidence(monkeypatch):
    monkeypatch.setattr(od, "get_opponent_defensive_profile", lambda *a, **k: {**PROFILE, "GP": 5, "PRIOR_GAMES": 20.0})
    r = od.compute(1, "player_rebounds")
    assert r.confidence == 0.75 and any("Early season" in e for e in r.evidence)


def test_no_profile(monkeypatch):
    monkeypatch.setattr(od, "get_opponent_defensive_profile", lambda *a, **k: None)
    assert od.compute(1, "player_points").confidence == 0


def test_team_stat_confidence():
    assert od.team_stat_confidence(40, 0) == 1.0
    assert od.team_stat_confidence(0, 25) == 0.7
    assert od.team_stat_confidence(15, 0) == 0.5
