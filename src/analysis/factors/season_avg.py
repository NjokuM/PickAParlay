"""
Factor 6: Season Averages (6%)
Current season per-game average vs the prop line.
Detects role changes by comparing full season avg to rolling 20-game avg.
If they diverge significantly (>15%), uses the rolling 20-game avg as primary.
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.models import FactorResult
from src.analysis.context_filter import compute_confidence


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
    side: str = "over",
) -> FactorResult:
    """
    df: full current-season game log (all teams, no context filter needed here —
        we want the full season picture, but still weight current team higher).
    """
    weight = config.FACTOR_WEIGHTS["season_avg"]

    if df.empty or stat_col not in df.columns:
        return FactorResult(
            name="Season Average",
            score=50.0,
            weight=weight,
            evidence=["No season data available."],
            data={},
            confidence=0.0,
        )

    # Use all current-season games, sorted most recent first
    df = df.copy()
    if "GAME_DATE" in df.columns:
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
        df = df.sort_values("GAME_DATE", ascending=False).reset_index(drop=True)

    full_avg = float(df[stat_col].mean())
    games_played = len(df)

    # Rolling 20-game average for role-change detection
    rolling_df = df.head(config.ROLE_CHANGE_WINDOW)
    rolling_avg = float(rolling_df[stat_col].mean()) if len(rolling_df) >= 5 else full_avg

    # Detect role change
    role_changed = False
    if full_avg > 0 and abs(rolling_avg - full_avg) / full_avg > config.ROLE_CHANGE_THRESHOLD:
        role_changed = True
        primary_avg = rolling_avg
    else:
        primary_avg = full_avg

    # Score: direction-aware — OVER wants avg above line, UNDER wants avg below line
    if line <= 0:
        score = 50.0
    elif side == "under":
        if primary_avg <= line:
            # avg below the line — excellent for UNDER
            margin_pct = (line - primary_avg) / line
            score = min(100.0, 50.0 + margin_pct * 100)
        else:
            # avg above line — works against the UNDER
            deficit_pct = (primary_avg - line) / line
            score = max(0.0, 50.0 - deficit_pct * 100)
    else:
        if primary_avg >= line:
            margin_pct = (primary_avg - line) / line
            score = min(100.0, 50.0 + margin_pct * 100)
        else:
            deficit_pct = (line - primary_avg) / line
            score = max(0.0, 50.0 - deficit_pct * 100)

    score = round(score, 1)
    confidence = compute_confidence(games_played, config.MIN_SAMPLE["season_avg"])

    # Direction-aware verdict string
    if side == "under":
        verdict = (
            f"✓ avg below line — favours UNDER ({primary_avg:.1f} vs {line})"
            if primary_avg <= line
            else f"✗ avg above line — works against UNDER ({primary_avg:.1f} vs {line})"
        )
    else:
        verdict = (
            f"✓ avg above line ({primary_avg:.1f} vs {line})"
            if primary_avg >= line
            else f"✗ avg below line ({primary_avg:.1f} vs {line})"
        )

    evidence: list[str] = []
    if role_changed:
        evidence.append(
            f"Role change detected — season avg {full_avg:.1f} vs recent {rolling_avg:.1f} "
            f"(using last {config.ROLE_CHANGE_WINDOW} games)"
        )
    evidence.append(
        f"Season avg: {full_avg:.1f} pts ({games_played} games) | "
        f"Using: {primary_avg:.1f} | Line: {line}"
    )
    evidence.append(verdict)
    if confidence < 1.0:
        evidence.append(f"Low confidence — {games_played} games played (need {config.MIN_SAMPLE['season_avg']})")

    return FactorResult(
        name="Season Average",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "full_season_avg": full_avg,
            "rolling_avg": rolling_avg,
            "primary_avg": primary_avg,
            "games_played": games_played,
            "role_changed": role_changed,
        },
        confidence=confidence,
    )
