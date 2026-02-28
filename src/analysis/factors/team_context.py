"""
Factor 5: Team Context (5%)
Team pace, recent win/loss form, back-to-back rest/fatigue — direction-aware.

OVER:  fast pace + good form + no B2B = high score
UNDER: slow pace = fewer possessions = harder to exceed line (pace inverted);
       B2B fatigue = fewer stat opportunities = slight boost for UNDER
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import config
from src.models import FactorResult
from src.api.nba_stats import get_team_pace_rank, get_team_recent_form


def compute(
    team_id: int,
    team_abbr: str,
    season: str | None = None,
    side: str = "over",
) -> FactorResult:
    if season is None:
        season = config.DEFAULT_SEASON
    weight = config.FACTOR_WEIGHTS["team_context"]

    form = get_team_recent_form(team_id, season=season)
    pace_data = get_team_pace_rank(team_id, season=season)

    evidence: list[str] = []
    score = 50.0  # baseline

    # Win/loss form contribution (last 5 games)
    wins = form.get("wins", 0)
    losses = form.get("losses", 0)
    streak = form.get("streak", "N/A")
    total = wins + losses
    if total > 0:
        form_score = (wins / total) * 100
        score = 0.5 * score + 0.5 * form_score
        evidence.append(f"Recent form: {wins}W-{losses}L (last {total} games), streak: {streak}")
    else:
        evidence.append("Recent form: no data")

    # Pace contribution — direction-aware
    if pace_data:
        pace_val, pace_rank = pace_data
        n_teams = 30
        pace_label = "fast" if pace_rank <= 10 else "mid" if pace_rank <= 20 else "slow"
        # Rank 1 = fastest → over_pace_score near 100; Rank 30 = slowest → near 0
        over_pace_score = ((n_teams - pace_rank) / (n_teams - 1)) * 100
        if side == "under":
            # Slow pace = fewer possessions = harder to accumulate stats = GOOD for UNDER
            pace_score = 100.0 - over_pace_score
            evidence.append(
                f"Pace: {pace_val:.1f} (rank {pace_rank}/30 — {pace_label})"
                + (" — slow pace favours UNDER" if pace_rank > 20 else "")
            )
        else:
            pace_score = over_pace_score
            evidence.append(f"Pace: {pace_val:.1f} (rank {pace_rank}/30 — {pace_label})")
        score = 0.6 * score + 0.4 * pace_score
    else:
        evidence.append("Pace data unavailable")

    # Rest / schedule fatigue — direction-aware
    rest_days = form.get("rest_days", 2)
    games_in_4 = form.get("games_in_last_4", 1)

    if form.get("back_to_back"):
        if side == "under":
            score = min(100.0, score * 1.10)
            evidence.append("B2B tonight — fatigue favours UNDER (fewer stat opportunities)")
        else:
            score *= 0.85
            evidence.append("⚠️  Playing on back-to-back (rest penalty applied)")
    elif games_in_4 >= 3:
        # Heavy schedule: 3+ games in 4 nights (not a strict B2B but still fatiguing)
        if side == "under":
            score = min(100.0, score * 1.05)
            evidence.append(f"Heavy schedule ({games_in_4} games in 4 nights) — slight UNDER boost")
        else:
            score *= 0.90
            evidence.append(f"⚠️  Heavy schedule ({games_in_4} games in 4 nights) — fatigue penalty")
    elif rest_days >= 2:
        # Extra rest: 2+ days off → player should be fresher
        if side == "over":
            score = min(100.0, score * 1.05)
            evidence.append(f"Well-rested ({rest_days} days off) — slight OVER boost")
        else:
            score *= 0.95
            evidence.append(f"Well-rested ({rest_days} days off) — slightly works against UNDER")
    else:
        evidence.append(f"Normal rest ({rest_days} day{'s' if rest_days != 1 else ''} off) ✓")

    score = round(min(100.0, max(0.0, score)), 1)

    return FactorResult(
        name="Team Context",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "wins": wins,
            "losses": losses,
            "streak": streak,
            "pace": pace_data,
            "back_to_back": form.get("back_to_back", False),
            "rest_days": rest_days,
            "games_in_last_4": games_in_4,
        },
        confidence=1.0,
    )
