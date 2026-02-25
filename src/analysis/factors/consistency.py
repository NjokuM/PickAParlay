"""
Factor 1: Consistency (38%)
Floor analysis + recency-weighted hit rate over last 10 games.
Primary signal: is the player's floor above the line?
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.models import FactorResult
from src.analysis.context_filter import compute_confidence, effective_sample_size


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
) -> FactorResult:
    """
    df: context-filtered game log with CTX_WEIGHT column.
    stat_col: column name (e.g. "PTS") or computed combo column.
    line: the prop line to beat.
    """
    weight = config.FACTOR_WEIGHTS["consistency"]

    if df.empty or stat_col not in df.columns:
        return FactorResult(
            name="Consistency",
            score=0.0,
            weight=weight,
            evidence=["No game log data available."],
            data={},
            confidence=0.0,
        )

    # Drop zero-weight rows, take last 10 non-OT games where possible
    valid = df[df.get("CTX_WEIGHT", pd.Series([1.0] * len(df))) > 0].copy()
    if "IS_OT" in valid.columns:
        non_ot = valid[~valid["IS_OT"]]
        if len(non_ot) >= 5:
            valid = non_ot

    valid = valid.head(10)
    values = valid[stat_col].tolist()
    weights = config.RECENCY_WEIGHTS_10[: len(values)]
    # Normalise weights in case we have fewer than 10 games
    w_sum = sum(weights)
    weights = [w / w_sum for w in weights]

    if not values:
        return FactorResult(
            name="Consistency",
            score=0.0,
            weight=weight,
            evidence=["Insufficient data after context filtering."],
            data={},
            confidence=0.0,
        )

    floor_value = min(values)
    hits = [v > line for v in values]

    # Weighted hit rate
    weighted_hit_rate = sum(w * int(h) for w, h in zip(weights, hits))

    # Floor contribution
    if floor_value >= line:
        floor_contrib = 1.0
    else:
        floor_contrib = max(0.0, floor_value / line) if line > 0 else 0.0

    score = (0.5 * weighted_hit_rate + 0.5 * floor_contrib) * 100.0
    score = round(min(100.0, score), 1)

    eff_sample = effective_sample_size(valid)
    confidence = compute_confidence(eff_sample, config.MIN_SAMPLE["consistency"])

    # Evidence
    vals_str = ", ".join(str(round(v, 1)) for v in values)
    hit_count = sum(hits)
    total = len(values)
    ot_flag = " (OT games excluded)" if "IS_OT" in df.columns else ""
    evidence = [
        f"Last {total} games{ot_flag}: {vals_str}",
        f"{hit_count}/{total} exceeded {line} (line)",
        f"Floor={round(floor_value, 1)} {'✓ above line' if floor_value >= line else '✗ below line'}",
        f"Weighted hit rate: {weighted_hit_rate:.0%}",
    ]
    if confidence < 1.0:
        evidence.append(f"Low confidence — only {eff_sample:.1f} effective games (need {config.MIN_SAMPLE['consistency']})")

    return FactorResult(
        name="Consistency",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "values": values,
            "floor": floor_value,
            "hit_rate": weighted_hit_rate,
            "hits": hit_count,
            "total": total,
        },
        confidence=confidence,
    )
