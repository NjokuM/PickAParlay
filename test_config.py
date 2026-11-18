from datetime import date

import pytest

import config


def test_factor_weights_sum_to_one():
    assert abs(sum(config.FACTOR_WEIGHTS.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("today,current,prev", [
    (date(2026, 10, 30), "2026-27", "2025-26"),
    (date(2026, 2, 1), "2025-26", "2024-25"),
])
def test_season_detection(monkeypatch, today, current, prev):
    class D(date):
        @classmethod
        def today(cls):
            return today
    monkeypatch.setattr(config, "date", D)
    assert config._nba_season(0) == current and config._nba_season(-1) == prev


def test_prev_season_and_playoffs(monkeypatch):
    assert config.prev_season_of("2026-27") == "2025-26" and config.prev_season_of("2000-01") == "1999-00"
    class D(date):
        @classmethod
        def today(cls):
            return date(2026, 5, 1)
    monkeypatch.setattr(config, "date", D)
    assert config.is_playoffs()


def test_api_keys_pool(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEYS", "a, b ,,c")
    assert config._parse_api_keys() == ["a", "b", "c"]
    monkeypatch.setenv("ODDS_API_KEYS", "")
    monkeypatch.setenv("ODDS_API_KEY", "single")
    assert config._parse_api_keys() == ["single"]


def test_market_helpers():
    assert config.get_base_market("player_points_alternate") == "player_points"
    assert config.get_market_label("player_threes_alternate") == "3-Pointers Made"
    assert config.get_market_label("unknown_market") == "unknown_market"


def test_model_version_changes_with_tunables(monkeypatch):
    v1 = config.model_version_id()
    assert v1.startswith(config.MODEL_VERSION + "+")
    monkeypatch.setitem(config.FACTOR_WEIGHTS, "consistency", 0.31)
    assert config.model_version_id() != v1
    monkeypatch.setattr(config.os.path, "dirname", lambda p: "/nonexistent")
    assert config._hit_model_fingerprint() == "missing"
