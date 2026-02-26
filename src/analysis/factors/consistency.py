"""
Factor 1: Consistency (38%)
Recency-weighted hit rate (60%) + floor/ceiling (25%) + weighted mean vs line (15%).
The mean component softens the impact of a single bad game tanking the floor contribution.
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
    side: str = "over",
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

    # For UNDER, a "hit" is staying below the line; the ceiling (max) replaces the floor (min)
    if side == "under":
        ceiling_value = max(values)
        hits = [v < line for v in values]
    else:
        floor_value = min(values)
        hits = [v > line for v in values]

    # Weighted hit rate
    weighted_hit_rate = sum(w * int(h) for w, h in zip(weights, hits))

    # Weighted mean
    weighted_mean = sum(w * v for w, v in zip(weights, values))

    if side == "under":
        # Ceiling contribution: how far below the line is the player's ceiling?
        if ceiling_value < line:
            bound_contrib = 1.0  # Even best game stays under — very favourable
        else:
            bound_contrib = max(0.0, (2 * line - ceiling_value) / line) if line > 0 else 0.0
        # Mean contribution (symmetric to OVER): high when mean is well below the line
        mean_contrib = min(1.0, max(0.0, (2 * line - weighted_mean) / line * 0.5)) if line > 0 else 0.5
    else:
        floor_value = min(values)
        # Floor contribution: how far above the line is the player's floor?
        if floor_value >= line:
            bound_contrib = 1.0
        else:
            bound_contrib = max(0.0, floor_value / line) if line > 0 else 0.0
        # Mean contribution: neutral (0.5) when mean = line, 1.0 when mean = 2×line
        mean_contrib = min(1.0, max(0.0, weighted_mean / line * 0.5)) if line > 0 else 0.5

    # 60% hit rate / 25% floor-or-ceiling / 15% mean vs line
    score = (0.60 * weighted_hit_rate + 0.25 * bound_contrib + 0.15 * mean_contrib) * 100.0
    score = round(min(100.0, score), 1)

    eff_sample = effective_sample_size(valid)
    confidence = compute_confidence(eff_sample, config.MIN_SAMPLE["consistency"])

    # Evidence
    vals_str = ", ".join(str(round(v, 1)) for v in values)
    hit_count = sum(hits)
    total = len(values)
    ot_flag = " (OT games excluded)" if "IS_OT" in df.columns else ""
    if side == "under":
        bound_label = f"Ceiling={round(ceiling_value, 1)} {'✓ below line' if ceiling_value < line else '✗ above line'}"
        direction_label = f"{hit_count}/{total} stayed below {line} (line)"
    else:
        floor_value = min(values)
        bound_label = f"Floor={round(floor_value, 1)} {'✓ above line' if floor_value >= line else '✗ below line'}"
        direction_label = f"{hit_count}/{total} exceeded {line} (line)"
    mean_vs_line = "above" if weighted_mean >= line else "below"
    evidence = [
        f"Last {total} games{ot_flag}: {vals_str}",
        direction_label,
        f"Mean={round(weighted_mean, 1)} ({mean_vs_line} {line}), {bound_label}",
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
            "floor": min(values) if side == "over" else None,
            "ceiling": max(values) if side == "under" else None,
            "mean": round(weighted_mean, 2),
            "hit_rate": weighted_hit_rate,
            "hits": hit_count,
            "total": total,
            "side": side,
        },
        confidence=confidence,
    )
