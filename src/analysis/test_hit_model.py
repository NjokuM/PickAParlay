import math

import pytest

from src.analysis import hit_model


def f(p=0.5, **extra):
    return {"mkt_logit": math.log(p / (1 - p)), "line_log": math.log(20.5), **extra}


def test_market_price_is_the_starting_point():
    # Offset model: a strong favourite stays strong, an underdog stays weak
    assert hit_model.predict_over("player_points", f(0.85)) > 0.75
    assert hit_model.predict_over("player_points", f(0.15)) < 0.25
    assert hit_model.predict_over("player_points", f(0.85)) > hit_model.predict_over("player_points", f(0.5))


def test_unknown_market_or_missing_price():
    assert hit_model.predict_over("player_blocks", f()) is None
    assert hit_model.predict_over("player_points", {"line_log": 1.0}) is None


def test_design_row_clips_and_defaults():
    m = hit_model._load()
    row = hit_model.design_row("player_points", {"z_season": 1e6}, m["scale"], m["deep_features"])
    assert len(row) == len(hit_model.design_columns(m["deep_features"]))
    assert max(row) <= hit_model.Z_CLIP
    assert row[hit_model.COMMON.index("z_last10")] == 0.0        # missing → average


def test_contributions_and_info():
    c = hit_model.contributions("player_points", f(z_season=2.0, teammates_out=3.0), top=3)
    assert len(c) == 3 and all(not name.startswith("is_") for name, _ in c)
    assert hit_model.model_info()["special_edge_min"] > 0


def test_missing_coefficients(monkeypatch):
    monkeypatch.setattr(hit_model, "_model", None)
    monkeypatch.setattr(hit_model, "_COEFS_PATH", "/nonexistent.json")
    assert hit_model.predict_over("player_points", f()) is None
    assert hit_model.contributions("player_points", f()) == []
