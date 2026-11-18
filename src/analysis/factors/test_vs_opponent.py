import pandas as pd

from src.analysis.factors import vs_opponent


def test_matchup_history_and_team_h2h(make_log):
    rec = {"wins": 2, "losses": 0, "avg_margin": 10, "games": 2}
    r = vs_opponent.compute(make_log([30] * 5, opp="NYK"), "PTS", 20.5, "NYK", "BOS", rec)
    assert r.score > 60 and r.data["hit_rate"] == 1.0 and "2W-0L" in r.evidence[-1]


def test_under_and_shrinkage_with_one_game(make_log):
    r = vs_opponent.compute(make_log([30], opp="NYK"), "PTS", 20.5, "NYK", "BOS", side="under")
    assert r.score < 50 and r.confidence < 1


def test_no_history_uses_team_record(make_log):
    r = vs_opponent.compute(make_log([30] * 3, opp="MIA"), "PTS", 20.5, "NYK", "BOS",
                            {"wins": 0, "losses": 2, "avg_margin": -10, "games": 2})
    assert r.confidence == 0.2 and r.score < 50
    assert vs_opponent._team_h2h_score(None) == 50 and "no data" in vs_opponent._team_h2h_evidence(None, "NYK")


def test_zero_weight_rows(make_log, monkeypatch):
    df = make_log([30] * 2, opp="NYK").assign(CTX_WEIGHT=0.0)
    monkeypatch.setattr(vs_opponent, "filter_vs_opponent", lambda d, *a: d)
    assert vs_opponent.compute(df, "PTS", 20.5, "NYK", "BOS").confidence == 0
