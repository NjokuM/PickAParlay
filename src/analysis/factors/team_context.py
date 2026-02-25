"""
Factor 5: Team Context (7%)
Team pace, recent win/loss form, back-to-back rest penalty.
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
    season: str = "2024-25",
) -> FactorResult:
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

    # Pace contribution — higher pace = more possessions = more counting stats
    if pace_data:
        pace_val, pace_rank = pace_data
        n_teams = 30
        # Rank 1 = fastest → score near 100; Rank 30 = slowest → score near 10
        pace_score = ((n_teams - pace_rank) / (n_teams - 1)) * 100
        score = 0.6 * score + 0.4 * pace_score
        evidence.append(f"Pace: {pace_val:.1f} (rank {pace_rank}/30 — {'fast' if pace_rank <= 10 else 'mid' if pace_rank <= 20 else 'slow'})")
    else:
        evidence.append("Pace data unavailable")

    # Back-to-back penalty
    if form.get("back_to_back"):
        score *= 0.85
        evidence.append("⚠️  Playing on back-to-back (rest penalty applied)")
    else:
        evidence.append("No back-to-back tonight ✓")

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
        },
        confidence=1.0,
    )
