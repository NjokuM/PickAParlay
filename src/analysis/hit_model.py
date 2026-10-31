"""
Hit-probability model: the chance a prop hits, used as the value score.

One pooled logistic model across all markets (trained in research/hit_model/,
coefficients in hit_model_coefs.json). It starts from the bookmaker's no-vig
price — the strongest single predictor — and adjusts it with player form,
context (teammates/opponents out, rest, pace) and market-specific opportunity
stats (usage, free-throw rate, rebound chances, potential assists, shot
profile…). Pooling markets was the only setup that held up when tested on
later weeks than it was trained on; per-market models overfit.

The design matrix is defined here and used by both training and live
grading, so they can't drift apart.
"""
from __future__ import annotations

import json
import math
import os

# gp_log (games played) is deliberately left out: trained on March–April it
# only proxied time of season, and early-season values sit far outside it.
COMMON = ["line_log", "z_season", "z_last10", "z_last5", "z_minadj", "hit_season",
          "hit_last10", "nb_logit", "min_trend", "home", "b2b", "teammates_out",
          "opp_out", "pace_idx", "z_opportunity"]
Z_CLIP = 3.0   # standardised inputs are clipped so one unusual value can't dominate
MARKETS = ["player_assists", "player_points", "player_points_assists", "player_points_rebounds",
           "player_points_rebounds_assists", "player_rebounds", "player_rebounds_assists",
           "player_threes"]

_COEFS_PATH = os.path.join(os.path.dirname(__file__), "hit_model_coefs.json")
_model: dict | None = None


# The bookmaker's no-vig log-odds (features["mkt_logit"]) is an OFFSET: the
# model starts from the market's own probability, unclipped and at full
# strength, and learns only adjustments to it. (Learning a slope on main
# lines — all priced ~35-65% — shrank it to ~0.4, so an 82% alt/custom line
# came out near 51%.)


def design_columns(deep_features: list[str]) -> list[str]:
    return COMMON + [f"is_{m}" for m in MARKETS[1:]] + list(deep_features)


def design_row(market: str, f: dict, scale: dict, deep_features: list[str]) -> list[float]:
    """
    One row of the design matrix. Common features are z-scored over all
    markets; deep (market-specific) features are z-scored over the markets
    they apply to and 0 elsewhere, so they only move their own markets.
    Missing values are treated as average (0).
    """
    def z(c: str) -> float:
        if c not in f:
            return 0.0
        mu, sd = scale[c]
        return max(-Z_CLIP, min(Z_CLIP, (f[c] - mu) / sd))

    row = [z(c) for c in COMMON]
    row += [1.0 if market == m else 0.0 for m in MARKETS[1:]]
    row += [z(c) for c in deep_features]
    return row


def _load() -> dict | None:
    global _model
    if _model is None and os.path.exists(_COEFS_PATH):
        with open(_COEFS_PATH) as fh:
            _model = json.load(fh)
    return _model


def model_info() -> dict:
    m = _load() or {}
    return {k: m.get(k) for k in ("version", "trained_at", "rows", "dates", "special_edge_min")}


def predict_over(market: str, features: dict) -> float | None:
    """Calibrated P(stat > line), or None if the model or market isn't available."""
    m = _load()
    if not m or market not in MARKETS or "mkt_logit" not in features:
        return None
    row = design_row(market, features, m["scale"], m["deep_features"])
    adj = m["intercept"] + sum(w * x for w, x in zip(m["coef"], row))
    a, b = m["calibration"]                     # recalibrates the adjustment only
    z = features["mkt_logit"] + a + b * adj
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))


def contributions(market: str, features: dict, top: int = 4) -> list[tuple[str, float]]:
    """The factors pushing this prop's over-probability most (logit units, + = towards OVER)."""
    m = _load()
    if not m:
        return []
    cols = design_columns(m["deep_features"])
    row = design_row(market, features, m["scale"], m["deep_features"])
    b = m["calibration"][1]
    contrib = [(c, b * w * x) for c, w, x in zip(cols, m["coef"], row)
               if not c.startswith("is_")]
    return sorted(contrib, key=lambda t: -abs(t[1]))[:top]
