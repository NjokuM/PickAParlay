"""
Return-From-Injury Detector

Analyses a player's game log to detect whether they recently returned
from an extended absence (7+ days).  Players easing back after injury
typically face minutes restrictions and underperform season averages —
this module quantifies that risk so the grading pipeline can penalise
OVER bets and boost UNDER confidence.

Used by prop_grader.py after fetching the game log and before computing
individual factors.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------
_MIN_ABSENCE_DAYS = 7      # gap must be at least this many days to count
_SCAN_DEPTH = 15            # how many recent games to scan for a gap
_NORMAL_MINUTES_PCT = 0.85  # >=85% of avg minutes = "back to normal"


def detect_return_from_injury(
    df: pd.DataFrame,
) -> dict:
    """
    Scan a player's game log (sorted most-recent first) for a recent
    absence of >= 7 days between games.

    Parameters
    ----------
    df : pd.DataFrame
        Player game log with ``GAME_DATE`` (datetime) and ``MIN`` (float)
        columns, sorted descending by date.

    Returns
    -------
    dict with keys:
        is_returning       : bool   - True if a recent absence was detected
        days_absent        : int    - length of the gap in days (0 if none)
        games_since_return : int    - games played after the gap
        minutes_pct_of_avg : float  - recent minutes as fraction of season avg
        confidence_penalty : float  - multiply into consistency confidence (1.0 = no change)
        injury_score_modifier : float - add to injury score (negative = penalise OVER)
        evidence           : list[str]
    """
    no_issue: dict = {
        "is_returning": False,
        "days_absent": 0,
        "games_since_return": 0,
        "minutes_pct_of_avg": 1.0,
        "confidence_penalty": 1.0,
        "injury_score_modifier": 0.0,
        "evidence": [],
    }

    if df.empty or "GAME_DATE" not in df.columns or "MIN" not in df.columns:
        return no_issue

    # Ensure we work with the first _SCAN_DEPTH rows (most recent games)
    recent = df.head(_SCAN_DEPTH).copy()
    if len(recent) < 3:
        return no_issue

    # Parse dates if needed
    dates = pd.to_datetime(recent["GAME_DATE"], errors="coerce")
    if dates.isna().all():
        return no_issue

    dates = dates.tolist()

    # Find the first large gap (scan from most recent backward)
    gap_index = None  # index *after* which the gap occurs
    days_absent = 0
    for i in range(len(dates) - 1):
        gap = (dates[i] - dates[i + 1]).days
        if gap >= _MIN_ABSENCE_DAYS:
            gap_index = i
            days_absent = gap
            break

    if gap_index is None:
        return no_issue

    # Count games since the player returned (games BEFORE the gap in the list)
    games_since_return = gap_index + 1  # 0-indexed: if gap_index=0, player just came back (1 game)

    # Compare recent minutes to season average
    minutes = recent["MIN"].dropna()
    if minutes.empty or minutes.mean() == 0:
        minutes_pct = 1.0
    else:
        season_avg_min = df["MIN"].dropna().mean()
        return_avg_min = minutes.head(games_since_return).mean()
        minutes_pct = return_avg_min / season_avg_min if season_avg_min > 0 else 1.0

    # Determine penalty tier
    confidence_penalty = 1.0
    injury_score_modifier = 0.0
    evidence: list[str] = []

    if games_since_return <= 2:
        # Heavy penalty — just came back
        confidence_penalty = 0.4
        injury_score_modifier = -25.0
        evidence.append(
            f"⚠️ Returning from {days_absent}-day absence — only {games_since_return} game(s) back"
        )
        if minutes_pct < _NORMAL_MINUTES_PCT:
            evidence.append(
                f"Minutes at {minutes_pct:.0%} of season average — likely restricted"
            )
    elif games_since_return <= 5:
        # Moderate penalty — still ramping up
        confidence_penalty = 0.65
        injury_score_modifier = -15.0
        evidence.append(
            f"⚠️ Recently returned from {days_absent}-day absence — {games_since_return} games back"
        )
        if minutes_pct < _NORMAL_MINUTES_PCT:
            evidence.append(
                f"Minutes at {minutes_pct:.0%} of season average — still ramping up"
            )
    elif games_since_return <= 8 and minutes_pct < _NORMAL_MINUTES_PCT:
        # Light penalty — back a while but minutes still restricted
        confidence_penalty = 0.85
        injury_score_modifier = -8.0
        evidence.append(
            f"Returned from {days_absent}-day absence {games_since_return} games ago"
        )
        evidence.append(
            f"Minutes at {minutes_pct:.0%} of season average — not yet fully ramped"
        )
    else:
        # No penalty — player is back to normal
        return no_issue

    return {
        "is_returning": True,
        "days_absent": days_absent,
        "games_since_return": games_since_return,
        "minutes_pct_of_avg": round(minutes_pct, 3),
        "confidence_penalty": confidence_penalty,
        "injury_score_modifier": injury_score_modifier,
        "evidence": evidence,
    }
