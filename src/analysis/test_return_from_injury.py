import pandas as pd

from src.analysis.return_from_injury import detect_return_from_injury


def log_with_gap(games_back, gap_days=14, minutes_back=20.0, minutes_before=32.0, total=15):
    dates, d = [], pd.Timestamp("2026-03-31")
    for i in range(total):
        dates.append(d)
        d -= pd.Timedelta(days=gap_days if i == games_back - 1 else 2)
    mins = [minutes_back] * games_back + [minutes_before] * (total - games_back)
    return pd.DataFrame({"GAME_DATE": dates, "MIN": mins})


def test_no_gap_means_no_issue(make_log):
    assert detect_return_from_injury(make_log(n=10))["is_returning"] is False


def test_just_returned_heavy_penalty():
    r = detect_return_from_injury(log_with_gap(1))
    assert r["is_returning"] and r["games_since_return"] == 1 and r["days_absent"] == 14
    assert r["confidence_penalty"] == 0.4 and r["injury_score_modifier"] == -25
    assert any("restricted" in e for e in r["evidence"])


def test_ramping_up_moderate_penalty():
    r = detect_return_from_injury(log_with_gap(4))
    assert r["confidence_penalty"] == 0.65 and any("ramping" in e for e in r["evidence"])


def test_back_a_while_but_restricted_minutes():
    r = detect_return_from_injury(log_with_gap(7))
    assert r["confidence_penalty"] == 0.85


def test_back_to_normal_minutes_no_penalty():
    assert detect_return_from_injury(log_with_gap(7, minutes_back=32))["is_returning"] is False
    assert detect_return_from_injury(log_with_gap(10))["is_returning"] is False


def test_bad_input():
    assert detect_return_from_injury(pd.DataFrame())["is_returning"] is False
    assert detect_return_from_injury(pd.DataFrame({"GAME_DATE": ["x", "y", "z"], "MIN": [1, 2, 3]}))["is_returning"] is False
    assert detect_return_from_injury(log_with_gap(1, total=2))["is_returning"] is False
