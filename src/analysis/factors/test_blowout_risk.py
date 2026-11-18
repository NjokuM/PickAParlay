from src.analysis.factors import blowout_risk as br


def test_no_data_is_neutral():
    assert br.compute(None, 0, True, True, "player_points").confidence == 0


def test_big_spread_and_margins_trigger_danger_zone(monkeypatch):
    monkeypatch.setattr(br, "get_team_avg_win_margin", lambda *a, **k: 20.0)
    over = br.compute(-18.0, 18.0, False, False, "player_threes", 1, 2)
    assert over.score < 70 and any("High blowout risk" in e for e in over.evidence)
    under = br.compute(-18.0, 18.0, False, False, "player_threes", 1, 2, side="under")
    assert under.score > 55


def test_close_game_low_risk(monkeypatch):
    monkeypatch.setattr(br, "get_team_avg_win_margin", lambda *a, **k: 0.0)
    r = br.compute(-1.5, 0.0, True, True, "player_points", 1, 2)
    assert r.score > 95 and any("acceptable" in e for e in r.evidence)
    assert any("unavailable" in e for e in br.compute(None, 5.0, True, True, "player_points", 1, 2).evidence)
