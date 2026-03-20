"""
Factor: Opponent Defense (15%)
Uses the opposing team's defensive stats (points/assists/rebounds/3PM allowed per game)
to assess how favourable this matchup is for the prop.

Direction-aware:
  OVER:  bad opponent defense = high score (they allow lots of stats)
  UNDER: good opponent defense = high score (they suppress stats)

Includes market-specific pace adjustment:
  - Rebounds favour fast-pace opponents (+boost for OVER)
  - Assists/PRA favour slow-pace opponents (-penalty for fast OVER)
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import config
from src.models import FactorResult
from src.api.nba_stats import get_opponent_defensive_profile

# Market → which defensive stat to check
DEFENSIVE_STAT_MAP: dict[str, str] = {
    "player_points":                  "OPP_PTS",
    "player_assists":                 "OPP_AST",
    "player_rebounds":                "OPP_REB",
    "player_threes":                  "OPP_FG3M",
    "player_points_rebounds_assists":  "OPP_PTS",   # PRA driven by points
    "player_points_rebounds":          "OPP_PTS",
    "player_points_assists":           "OPP_PTS",
    "player_rebounds_assists":         "OPP_REB",
}

# Market-specific pace modifier (from empirical analysis)
# Positive = fast pace helps OVER; Negative = fast pace hurts OVER
PACE_MARKET_MODIFIER: dict[str, float] = {
    "player_rebounds":                 0.08,   # +10.9pp gap for fast games
    "player_assists":                 -0.06,   # -19.2pp gap for fast games
    "player_points_rebounds_assists":  -0.04,   # PRA slightly favours slow
    "player_threes":                  -0.03,   # 3PM slightly favours slow
    "player_rebounds_assists":        -0.04,   # RA favours slow
    # Points, PR, PA: pace-neutral (0.0 default)
}


def compute(
    opponent_team_id: int,
    market: str,
    side: str = "over",
    season: str | None = None,
) -> FactorResult:
    """
    Score the opponent's defensive matchup for this market.
    """
    if season is None:
        season = config.DEFAULT_SEASON
    weight = config.FACTOR_WEIGHTS.get("opponent_defense", 0.15)

    profile = get_opponent_defensive_profile(opponent_team_id, season=season)
    if profile is None:
        return FactorResult(
            name="Opponent Defense",
            score=50.0,
            weight=weight,
            evidence=["Opponent defensive stats unavailable — neutral score"],
            data={},
            confidence=0.0,
        )

    # Get the relevant defensive stat and its percentile
    stat_key = DEFENSIVE_STAT_MAP.get(market, "OPP_PTS")
    stat_val = profile.get(stat_key, 0)
    stat_pct = profile.get(f"{stat_key}_pct", 0.5)  # 0 = best defense, 1 = worst

    # Apply pace modifier
    pace_mod = PACE_MARKET_MODIFIER.get(market, 0.0)
    pace_pct = profile.get("PACE_pct", 0.5)  # 0 = slowest, 1 = fastest
    pace_adj = pace_mod * pace_pct

    team_name = profile.get("TEAM_NAME", "Unknown")
    evidence: list[str] = []

    if side == "over":
        # Worst defense (high pct) = high score for overs
        raw = stat_pct + pace_adj
        raw = max(0.0, min(1.0, raw))
        score = round(30.0 + raw * 70.0, 1)
        evidence.append(
            f"vs {team_name}: allows {stat_val:.1f} {stat_key.replace('OPP_', '')} per game "
            f"(percentile: {stat_pct:.0%} — {'weak' if stat_pct > 0.6 else 'strong' if stat_pct < 0.4 else 'average'} defense)"
        )
    else:
        # Best defense (low pct) = high score for unders
        raw = (1.0 - stat_pct) - pace_adj
        raw = max(0.0, min(1.0, raw))
        score = round(30.0 + raw * 70.0, 1)
        evidence.append(
            f"vs {team_name}: allows {stat_val:.1f} {stat_key.replace('OPP_', '')} per game "
            f"(percentile: {stat_pct:.0%} — {'strong' if stat_pct < 0.4 else 'weak' if stat_pct > 0.6 else 'average'} defense for UNDER)"
        )

    # Add pace context if significant
    if abs(pace_adj) > 0.01:
        pace_val = profile.get("PACE", 100.0)
        direction = "boost" if pace_adj > 0 else "penalty"
        evidence.append(
            f"Pace adjustment: {pace_val:.1f} ({pace_pct:.0%} percentile) "
            f"→ {direction} of {abs(pace_adj):.2f} for this market"
        )

    evidence.append(f"DEF Rating: {profile.get('DEF_RATING', 0):.1f}")

    return FactorResult(
        name="Opponent Defense",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "opponent": team_name,
            "stat_key": stat_key,
            "stat_val": stat_val,
            "stat_pct": stat_pct,
            "pace": profile.get("PACE", 100.0),
            "pace_pct": pace_pct,
            "pace_adj": pace_adj,
            "def_rating": profile.get("DEF_RATING", 0),
        },
        confidence=1.0,
    )
