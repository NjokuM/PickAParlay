"""
Value score compositor.
Combines factor results into a single weighted composite score.
Also runs suspicious line detection.
"""
from __future__ import annotations

import config
from src.models import FactorResult


NEUTRAL_SCORE = 50.0  # used when blending low-confidence factors


def compute_value_score(factors: list[FactorResult]) -> float:
    """
    Weighted composite. Low-confidence factor scores are blended toward neutral (50).
    Final score is 0–100.
    """
    if not factors:
        return 0.0

    total = 0.0
    total_weight = 0.0

    for f in factors:
        # Blend toward neutral based on confidence
        effective_score = f.score * f.confidence + NEUTRAL_SCORE * (1 - f.confidence)
        total += effective_score * f.weight
        total_weight += f.weight

    if total_weight == 0:
        return 0.0

    return round(total / total_weight, 1)


def label_recommendation(score: float) -> str:
    for threshold, label in config.SCORE_LABELS:
        if score >= threshold:
            return label
    return "Poor Value"


def detect_suspicious_line(
    line: float,
    season_avg: float | None,
) -> tuple[bool, str]:
    """
    Flag if the line looks like a trap (too easy or too hard vs season avg).
    Returns (is_suspicious, reason_string).
    """
    if season_avg is None or season_avg <= 0 or line <= 0:
        return False, ""

    diff_pct = (season_avg - line) / line

    if diff_pct > config.SUSPICIOUS_EASY_THRESHOLD:
        return (
            True,
            f"Line ({line}) is {diff_pct:.0%} below season avg ({season_avg:.1f}) — "
            "may be a trap line, verify manually",
        )

    if diff_pct < -config.SUSPICIOUS_HARD_THRESHOLD:
        hard_pct = abs(diff_pct)
        return (
            True,
            f"Line ({line}) is {hard_pct:.0%} above season avg ({season_avg:.1f}) — "
            "unusually high, verify manually",
        )

    return False, ""
