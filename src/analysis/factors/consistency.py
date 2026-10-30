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
from src.analysis import priors
from src.analysis.context_filter import compute_confidence, effective_sample_size


def _bound_contrib(bound: float, line: float, side: str) -> float:
    """Floor (OVER) / ceiling (UNDER) contribution, 0–1."""
    if line <= 0:
        return 0.0
    if side == "under":
        # How far below the line is the player's ceiling?
        if bound < line:
            return 1.0  # Even best game stays under — very favourable
        return max(0.0, (2 * line - bound) / line)
    # How far above the line is the player's floor?
    if bound >= line:
        return 1.0
    return max(0.0, bound / line)


def _mean_contrib(mean: float, line: float, side: str) -> float:
    """Neutral (0.5) when mean = line; 1.0 when mean = 2×line (OVER) or 0 (UNDER)."""
    if line <= 0:
        return 0.5
    if side == "under":
        return min(1.0, max(0.0, (2 * line - mean) / line * 0.5))
    return min(1.0, max(0.0, mean / line * 0.5))


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
    side: str = "over",
    prior_mu: float | None = None,
    prior_k: float = 0.0,
) -> FactorResult:
    """
    df: context-filtered game log with CTX_WEIGHT column.
    stat_col: column name (e.g. "PTS") or computed combo column.
    line: the prop line to beat.
    prior_mu / prior_k: early-season prior (src/analysis/priors.py) — projected
        mean from last season's per-minute rates, worth prior_k games. Each
        component is blended with what the prior implies.
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

    # Drop zero-weight rows, take last 10 games (OT games included — they are
    # high-stakes, full-minutes games, especially relevant in the playoffs)
    valid = df[df.get("CTX_WEIGHT", pd.Series([1.0] * len(df))) > 0].copy()
    valid = valid.head(10)
    values = valid[stat_col].tolist()

    # Combine positional recency weights with per-game playoff boost.
    # Playoff games (PLAYOFF_WEIGHT > 1.0) pull the weighted hit-rate and
    # mean toward recent playoff performance without discarding RS history.
    recency = config.RECENCY_WEIGHTS_10[: len(values)]
    if "PLAYOFF_WEIGHT" in valid.columns:
        po_boost = valid["PLAYOFF_WEIGHT"].tolist()[: len(values)]
    else:
        po_boost = [1.0] * len(values)
    combined = [r * p for r, p in zip(recency, po_boost)]
    w_sum = sum(combined)
    weights = [w / w_sum for w in combined]

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
        bound_value = ceiling_value
        hits = [v < line for v in values]
    else:
        floor_value = min(values)
        bound_value = floor_value
        hits = [v > line for v in values]

    # Weighted hit rate
    weighted_hit_rate = sum(w * int(h) for w, h in zip(weights, hits))

    # Weighted mean
    weighted_mean = sum(w * v for w, v in zip(weights, values))

    bound_contrib = _bound_contrib(bound_value, line, side)

    # Early-season prior: blend each component with what last season's
    # per-minute rates × this season's minutes imply, worth prior_k games
    # against the len(values) observed. Floor/ceiling use the prior's 10th/90th
    # percentile — roughly the min/max of a 10-game window.
    prior_share = 0.0
    if prior_mu is not None and prior_k > 0:
        prior_share = prior_k / (len(values) + prior_k)
        prior_hit = priors.prob_hit(prior_mu, stat_col, line, side)
        prior_bound = priors.quantile(prior_mu, stat_col, 0.9 if side == "under" else 0.1)
        weighted_hit_rate = (1 - prior_share) * weighted_hit_rate + prior_share * prior_hit
        bound_contrib = (1 - prior_share) * bound_contrib + prior_share * _bound_contrib(prior_bound, line, side)
        weighted_mean = (1 - prior_share) * weighted_mean + prior_share * prior_mu

    mean_contrib = _mean_contrib(weighted_mean, line, side)

    # 60% hit rate / 25% floor-or-ceiling / 15% mean vs line
    score = (0.60 * weighted_hit_rate + 0.25 * bound_contrib + 0.15 * mean_contrib) * 100.0
    score = round(min(100.0, score), 1)

    eff_sample = effective_sample_size(valid)
    confidence = compute_confidence(eff_sample, config.MIN_SAMPLE["consistency"])
    # Few games played: a short streak isn't full-confidence evidence on its own
    games_evidence = len(values) + (prior_k if prior_share > 0 else 0.0)
    confidence *= compute_confidence(games_evidence, config.CONSISTENCY_FULL_CONFIDENCE_GAMES)

    # Evidence
    vals_str = ", ".join(str(round(v, 1)) for v in values)
    hit_count = sum(hits)
    total = len(values)
    po_games = int(valid.get("IS_PLAYOFF_GAME", pd.Series([False] * len(valid))).sum())
    po_flag = f", {po_games} playoff" if po_games > 0 else ""
    if side == "under":
        bound_label = f"Ceiling={round(ceiling_value, 1)} {'✓ below line' if ceiling_value < line else '✗ above line'}"
        direction_label = f"{hit_count}/{total} stayed below {line} (line)"
    else:
        floor_value = min(values)
        bound_label = f"Floor={round(floor_value, 1)} {'✓ above line' if floor_value >= line else '✗ below line'}"
        direction_label = f"{hit_count}/{total} exceeded {line} (line)"
    mean_vs_line = "above" if weighted_mean >= line else "below"
    evidence = [
        f"Last {total} games{po_flag}: {vals_str}",
        direction_label,
        f"Mean={round(weighted_mean, 1)} ({mean_vs_line} {line}), {bound_label}",
        f"Weighted hit rate: {weighted_hit_rate:.0%}",
    ]
    if prior_share > 0:
        evidence.append(
            f"Blended {prior_share:.0%} with last-season prior "
            f"(projects {prior_mu:.1f}, worth {prior_k:.1f} games)"
        )
    if confidence < 1.0:
        evidence.append(
            f"Low confidence — {eff_sample:.1f} effective games, {games_evidence:.1f} games of evidence "
            f"(need {config.MIN_SAMPLE['consistency']} / {config.CONSISTENCY_FULL_CONFIDENCE_GAMES})"
        )

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
            "prior_mu": round(prior_mu, 2) if prior_share > 0 else None,
            "prior_share": round(prior_share, 3),
        },
        confidence=confidence,
    )
