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
from src.api.nba_stats import get_league_player_usage

# Fallback keyword list — used ONLY when league-wide stats are unavailable
_FALLBACK_STAR_KEYWORDS = ["harden", "doncic", "curry", "james", "giannis", "embiid",
                           "jokic", "durant", "tatum", "mitchell", "brown", "young",
                           "booker", "lillard", "george", "westbrook", "fox", "lavine"]

# Thresholds for dynamic high-usage detection
_HIGH_USAGE_MPG = 24.0    # starter-level minutes
_HIGH_USAGE_FGA = 12.0    # significant shot volume


def _is_high_usage(player_name: str) -> bool:
    """
    Check if a player is high-usage based on their season stats (MPG >= 24 or FGA >= 12).
    Falls back to the keyword list if league stats are unavailable.
    """
    usage = get_league_player_usage()
    if usage:
        key = player_name.strip().lower()
        stats = usage.get(key)
        if stats:
            return stats["mpg"] >= _HIGH_USAGE_MPG or stats["fga"] >= _HIGH_USAGE_FGA
        # Player not found in league stats — try fuzzy match on last name
        last_name = key.split()[-1] if key else ""
        for name, stats in usage.items():
            if last_name and last_name in name:
                if stats["mpg"] >= _HIGH_USAGE_MPG or stats["fga"] >= _HIGH_USAGE_FGA:
                    return True
        return False
    # Fallback: use keyword list when API data unavailable
    return any(kw in player_name.lower() for kw in _FALLBACK_STAR_KEYWORDS)


def compute(
    player_name: str,
    player_team_abbr: str,
    opponent_team_abbr: str,
    market: str,
    injury_reports: list[InjuryReport],
    side: str = "over",
) -> FactorResult:
    weight = config.FACTOR_WEIGHTS["injury"]

    # 1. Player's own status — OUT/DOUBTFUL: avoid regardless of side
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
        if side == "under":
            # QUESTIONABLE/PROBABLE for UNDER = likely plays limited minutes → fewer stat opportunities → GOOD
            # severity=0.5 (QUESTIONABLE) → +10 boost; severity=0.8 (PROBABLE) → +4 boost
            boost = (1.0 - severity) * 20.0
            score = min(100.0, score + boost)
            evidence.append(
                f"{player_name}: {player_status.upper()} — limited minutes likely, favours UNDER"
            )
        else:
            score *= severity
            evidence.append(f"{player_name}: {player_status.upper()} ({severity:.0%} health)")
    else:
        evidence.append(f"{player_name}: healthy ✓")

    # 2. Teammate injuries (same team as the player)
    teammate_injuries = get_team_injuries(player_team_abbr, injury_reports)
    teammate_impact = _assess_teammate_impact(
        player_name, market, teammate_injuries, evidence, side=side
    )
    score += teammate_impact

    # 3. Opponent key injuries
    opponent_injuries = get_team_injuries(opponent_team_abbr, injury_reports)
    opponent_impact = _assess_opponent_impact(market, opponent_injuries, evidence, side=side)
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
    side: str = "over",
) -> float:
    """
    Estimate how teammate injuries shift this player's counting stats.

    OVER: primary scorer out → ball handler gets more touches → PTS up, AST down.
    UNDER: effects are mirrored — more scoring load is BAD for UNDER PTS; fewer set plays
           means fewer assists which is GOOD for UNDER AST.
    """
    impact = 0.0
    for inj in teammate_injuries:
        if inj.player_name.lower() == player_name.lower():
            continue  # the player themselves
        if not is_player_unavailable(inj.status):
            continue

        is_star = _is_high_usage(inj.player_name)
        if not is_star:
            continue

        if "assists" in market:
            if side == "under":
                # Fewer set plays → fewer assists → GOOD for UNDER
                impact += 5
                evidence.append(
                    f"Teammate {inj.player_name} ({inj.status}) — fewer set plays, assists likely lower (favours UNDER)"
                )
            else:
                # Primary scorer out → fewer set plays → AST may drop → BAD for OVER
                impact -= 5
                evidence.append(
                    f"Teammate {inj.player_name} ({inj.status}) — fewer set plays, assists may drop"
                )
        elif "points" in market:
            if side == "under":
                # More scoring load → player expected to score MORE → BAD for UNDER
                impact -= 8
                evidence.append(
                    f"Teammate {inj.player_name} ({inj.status}) — increased scoring load (works against UNDER)"
                )
            else:
                # Star scorer out → player takes on more scoring load → GOOD for OVER
                impact += 8
                evidence.append(
                    f"Teammate {inj.player_name} ({inj.status}) — increased scoring load +"
                )
        else:
            evidence.append(f"Teammate {inj.player_name} ({inj.status})")

    return impact


def _assess_opponent_impact(
    market: str,
    opponent_injuries: list[InjuryReport],
    evidence: list[str],
    side: str = "over",
) -> float:
    """
    Key defender on opponent is out → easier scoring/assists (GOOD for OVER, BAD for UNDER).
    """
    impact = 0.0
    for inj in opponent_injuries:
        if not is_player_unavailable(inj.status):
            continue
        is_star = _is_high_usage(inj.player_name)
        if not is_star:
            continue

        if "points" in market or "rebounds" in market or "assists" in market or "pra" in market.lower():
            if side == "under":
                # Weakened opponent defence → easier scoring = BAD for UNDER
                impact -= 7
                evidence.append(
                    f"Opponent {inj.player_name} ({inj.status.upper()}) — weaker defence (works against UNDER)"
                )
            else:
                impact += 7
                evidence.append(
                    f"Opponent {inj.player_name} ({inj.status.upper()}) — defence weakened +"
                )

    return impact


def should_avoid(factor: FactorResult) -> bool:
    return bool(factor.data.get("avoid", False))
