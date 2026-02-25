"""
Factor 2: vs Opponent (20%)
Performance vs tonight's specific opponent.
Includes H2H team record and season recency weighting.
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.models import FactorResult
from src.analysis.context_filter import (
    filter_vs_opponent,
    compute_confidence,
    effective_sample_size,
)


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
    opponent_abbr: str,
    current_team_abbr: str,
    h2h_team_record: dict | None = None,
) -> FactorResult:
    """
    df: full game log (context_filter will slice it to vs-opponent rows).
    h2h_team_record: {"wins": int, "losses": int, "avg_margin": float, "games": int}
    """
    weight = config.FACTOR_WEIGHTS["vs_opponent"]

    h2h_df = filter_vs_opponent(df, opponent_abbr, current_team_abbr)

    if h2h_df.empty or stat_col not in h2h_df.columns:
        # No matchup history — use a neutral score blended with team H2H context
        team_h2h_score = _team_h2h_score(h2h_team_record)
        evidence = [
            f"No individual matchup history vs {opponent_abbr}.",
            _team_h2h_evidence(h2h_team_record, opponent_abbr),
        ]
        return FactorResult(
            name=f"vs {opponent_abbr}",
            score=round(team_h2h_score, 1),
            weight=weight,
            evidence=evidence,
            data={"team_h2h": h2h_team_record},
            confidence=0.2,
        )

    values = h2h_df[stat_col].tolist()
    ctx_weights = h2h_df.get("CTX_WEIGHT", pd.Series([1.0] * len(h2h_df))).tolist()

    # Weighted hit rate
    total_weight = sum(ctx_weights)
    if total_weight == 0:
        return _no_data_result(weight, opponent_abbr)

    weighted_hit_rate = sum(
        w * int(v > line) for v, w in zip(values, ctx_weights)
    ) / total_weight

    # Weighted average
    weighted_avg = sum(v * w for v, w in zip(values, ctx_weights)) / total_weight

    # Score: hit rate (60%) + how far above the line the avg sits (40%)
    avg_above = max(0.0, (weighted_avg - line) / line) if line > 0 else 0.0
    avg_score = min(1.0, 0.5 + avg_above)
    score = (0.6 * weighted_hit_rate + 0.4 * avg_score) * 100.0

    # Blend with team H2H context (adds context to individual stats)
    team_h2h_score = _team_h2h_score(h2h_team_record)
    score = 0.80 * score + 0.20 * team_h2h_score
    score = round(min(100.0, score), 1)

    eff_sample = effective_sample_size(h2h_df)
    confidence = compute_confidence(eff_sample, config.MIN_SAMPLE["vs_opponent"])

    vals_str = ", ".join(str(round(v, 1)) for v in values)
    hit_count = sum(1 for v in values if v > line)
    evidence = [
        f"vs {opponent_abbr}: {len(values)} game(s), avg {weighted_avg:.1f}, {hit_count}/{len(values)} hit",
        f"Values: {vals_str}",
        _team_h2h_evidence(h2h_team_record, opponent_abbr),
    ]
    if confidence < 1.0:
        evidence.append(f"Low confidence — {eff_sample:.1f} effective games (need {config.MIN_SAMPLE['vs_opponent']})")

    return FactorResult(
        name=f"vs {opponent_abbr}",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "values": values,
            "weighted_avg": weighted_avg,
            "hit_rate": weighted_hit_rate,
            "team_h2h": h2h_team_record,
        },
        confidence=confidence,
    )


def _no_data_result(weight: float, opp: str) -> FactorResult:
    return FactorResult(
        name=f"vs {opp}",
        score=50.0,
        weight=weight,
        evidence=[f"No usable matchup data vs {opp}."],
        data={},
        confidence=0.0,
    )


def _team_h2h_score(record: dict | None) -> float:
    """Convert team H2H record into a 0–100 score."""
    if not record or record.get("games", 0) == 0:
        return 50.0
    wins = record.get("wins", 0)
    games = record.get("games", 1)
    win_rate = wins / games
    avg_margin = record.get("avg_margin", 0)
    # Win rate (70%) + margin contribution (30%)
    margin_contrib = min(1.0, max(0.0, 0.5 + avg_margin / 20))
    return round((0.7 * win_rate + 0.3 * margin_contrib) * 100, 1)


def _team_h2h_evidence(record: dict | None, opp: str) -> str:
    if not record or record.get("games", 0) == 0:
        return f"Team H2H vs {opp}: no data"
    w, l, m, g = record["wins"], record["losses"], record["avg_margin"], record["games"]
    return f"Team H2H vs {opp}: {w}W-{l}L in {g} games, avg margin {m:+.1f}"
