"""
Factor 4: Injury Context (13%)
Scores the injury situation for the player and both teams.
  - Player themselves injured → score 0, flag AVOID
  - Key teammate out → may increase/decrease counting stats
  - Key opponent defender out → positive for scoring/assist props
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import config
from src.models import FactorResult, InjuryReport
from src.api.injury_api import (
    get_player_status,
    get_team_injuries,
    is_player_unavailable,
    injury_severity_score,
)

# Simplified list of high-usage / star players whose absence matters most
# The system uses a usage-proxy: any player with "star" role matters more
# In practice we check minutes/usage from stats — here we use a heuristic
_HIGH_USAGE_KEYWORDS = ["harden", "doncic", "curry", "james", "giannis", "embiid",
                        "jokic", "durant", "tatum", "mitchell", "brown", "young",
                        "booker", "lillard", "george", "westbrook", "fox", "lavine"]


def compute(
    player_name: str,
    player_team_abbr: str,
    opponent_team_abbr: str,
    market: str,
    injury_reports: list[InjuryReport],
) -> FactorResult:
    weight = config.FACTOR_WEIGHTS["injury"]

    # 1. Player's own status
    player_status = get_player_status(player_name, injury_reports)
    if is_player_unavailable(player_status):
        return FactorResult(
            name="Injury Context",
            score=0.0,
            weight=weight,
            evidence=[
                f"⚠️  {player_name} is {player_status.upper()} — DO NOT BET this prop",
            ],
            data={"player_status": player_status, "avoid": True},
            confidence=1.0,
        )

    evidence: list[str] = []
    score = 75.0  # baseline — player healthy, no relevant injuries

    if player_status:
        severity = injury_severity_score(player_status)
        score *= severity
        evidence.append(f"{player_name}: {player_status.upper()} ({severity:.0%} health)")
    else:
        evidence.append(f"{player_name}: healthy ✓")

    # 2. Teammate injuries (same team as the player)
    teammate_injuries = get_team_injuries(player_team_abbr, injury_reports)
    teammate_impact = _assess_teammate_impact(
        player_name, market, teammate_injuries, evidence
    )
    score += teammate_impact

    # 3. Opponent key injuries (positive for the player)
    opponent_injuries = get_team_injuries(opponent_team_abbr, injury_reports)
    opponent_impact = _assess_opponent_impact(market, opponent_injuries, evidence)
    score += opponent_impact

    score = round(max(0.0, min(100.0, score)), 1)

    return FactorResult(
        name="Injury Context",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "player_status": player_status,
            "teammate_injuries": [r.__dict__ for r in teammate_injuries],
            "opponent_injuries": [r.__dict__ for r in opponent_injuries],
            "avoid": False,
        },
        confidence=1.0,
    )


def _assess_teammate_impact(
    player_name: str,
    market: str,
    teammate_injuries: list[InjuryReport],
    evidence: list[str],
) -> float:
    """
    Estimate how teammate injuries shift this player's counting stats.
    A primary scorer out → ball handler gets more touches → AST may drop, PTS may rise.
    A secondary player out → neutral.
    """
    impact = 0.0
    for inj in teammate_injuries:
        if inj.player_name.lower() == player_name.lower():
            continue  # the player themselves
        if not is_player_unavailable(inj.status):
            continue

        is_star = any(kw in inj.player_name.lower() for kw in _HIGH_USAGE_KEYWORDS)
        if not is_star:
            continue

        if "assists" in market:
            # Primary scorer out → fewer set plays, assists likely drop
            impact -= 5
            evidence.append(
                f"Teammate {inj.player_name} ({inj.status}) — fewer set plays, assists may drop"
            )
        elif "points" in market:
            # Star scorer out → player takes on more scoring load
            impact += 8
            evidence.append(
                f"Teammate {inj.player_name} ({inj.status}) — increased scoring load +"
            )
        else:
            # Neutral for other markets
            evidence.append(f"Teammate {inj.player_name} ({inj.status})")

    return impact


def _assess_opponent_impact(
    market: str,
    opponent_injuries: list[InjuryReport],
    evidence: list[str],
) -> float:
    """
    Key defender/scorer on opponent is out → positive for scoring/assists.
    """
    impact = 0.0
    for inj in opponent_injuries:
        if not is_player_unavailable(inj.status):
            continue
        is_star = any(kw in inj.player_name.lower() for kw in _HIGH_USAGE_KEYWORDS)
        if not is_star:
            continue

        if "points" in market or "rebounds" in market or "assists" in market or "pra" in market.lower():
            impact += 7
            evidence.append(
                f"Opponent {inj.player_name} ({inj.status.upper()}) — defence weakened +"
            )

    return impact


def should_avoid(factor: FactorResult) -> bool:
    return bool(factor.data.get("avoid", False))
