"""
Factor: Blowout Risk (10%)
Uses the game spread + H2H margin history + team average win margin
to estimate how likely this game is to become a blowout.

Empirically redesigned with market-specific sensitivity multipliers:
  - Reb+Ast and 3PM are most damaged by blowouts (+27-35pp gap)
  - Points and basic combos are moderately affected (+14-16pp)

Direction-aware:
  OVER:  high blowout risk = starters pulled early = stats cut short = BAD (low score)
  UNDER: high blowout risk = starters sit = fewer stats = GOOD (moderate score)
         Data shows only ~4pp variance on UNDER, so we keep scoring flatter.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import config
from src.models import FactorResult
from src.api.nba_stats import get_team_avg_win_margin

# Market-specific blowout sensitivity multipliers (from empirical data)
# Higher = more affected by blowouts
MARKET_BLOWOUT_SENSITIVITY: dict[str, float] = {
    "player_rebounds_assists":         1.4,   # +35pp gap — most affected
    "player_threes":                   1.3,   # +27pp gap
    "player_points_assists":           1.1,   # +18pp gap
    "player_points_rebounds_assists":   1.0,   # +16pp — baseline
    "player_points":                   1.0,   # +15pp
    "player_rebounds":                 0.9,   # +14pp
    "player_assists":                  0.9,   # +14pp
    "player_points_rebounds":          0.8,   # +12pp — least affected
}


def compute(
    spread: float | None,
    h2h_avg_margin: float,
    player_team_is_favorite: bool,
    player_is_starter: bool,
    market: str,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
    season: str | None = None,
    side: str = "over",
) -> FactorResult:
    if season is None:
        season = config.DEFAULT_SEASON
    weight = config.FACTOR_WEIGHTS["blowout_risk"]

    evidence: list[str] = []

    # --- Early return when no data is available ---
    if spread is None and h2h_avg_margin == 0:
        return FactorResult(
            name="Blowout Risk",
            score=50.0,
            weight=weight,
            evidence=["Spread unavailable — blowout risk unknown, neutral score"],
            data={"blowout_risk": None, "spread": None, "h2h_avg_margin": 0},
            confidence=0.0,
        )

    # --- Blowout risk calculation (unchanged core) ---
    spread_abs = abs(spread) if spread is not None else 0.0
    spread_risk = min(1.0, spread_abs / config.BLOWOUT_SPREAD_NORMALISER)

    h2h_risk = min(1.0, abs(h2h_avg_margin) / config.BLOWOUT_SPREAD_NORMALISER)

    team_id = home_team_id if player_team_is_favorite else away_team_id
    team_style_risk = 0.0
    if team_id:
        avg_win_margin = get_team_avg_win_margin(team_id, season=season)
        team_style_risk = min(1.0, avg_win_margin / config.BLOWOUT_SPREAD_NORMALISER)
        if avg_win_margin > 0:
            evidence.append(f"Team avg win margin: +{avg_win_margin:.1f}")

    blowout_risk = (
        0.50 * spread_risk +
        0.30 * h2h_risk +
        0.20 * team_style_risk
    )

    if spread is not None:
        evidence.append(f"Spread: {spread:+.1f} → risk: {spread_risk:.0%}")
    else:
        evidence.append("Spread unavailable — using H2H + team style")

    evidence.append(f"H2H margin: {h2h_avg_margin:+.1f} → risk: {h2h_risk:.0%}")
    evidence.append(f"Combined blowout risk: {blowout_risk:.0%}")

    # --- OVER scoring: steeper penalty curve with market sensitivity ---
    market_mult = MARKET_BLOWOUT_SENSITIVITY.get(market, 1.0)

    if side == "over":
        if blowout_risk > config.BLOWOUT_RISK_CUTOFF:
            # Danger zone — strong penalty, scaled by market sensitivity
            base_penalty = 0.20 + blowout_risk * 0.25  # 0.34 to 0.45
            if not player_is_starter:
                base_penalty *= 1.3  # Bench players hit harder
            elif not player_team_is_favorite:
                base_penalty *= 1.1  # Underdog starters slightly worse
            penalty = min(0.55, base_penalty * market_mult)
            score = round((1.0 - penalty) * 100, 1)
            evidence.append(
                f"High blowout risk — penalty: {penalty:.0%} "
                f"(market sensitivity: {market_mult:.1f}x)"
            )
        else:
            # Low risk zone — mild linear penalty
            penalty = blowout_risk * 0.15 * market_mult
            score = round((1.0 - penalty) * 100, 1)
            evidence.append(f"Blowout risk acceptable ({blowout_risk:.0%})")
    else:
        # --- UNDER scoring: flatter curve (data shows only ~4pp variance) ---
        # Neutral at risk=0 → 55, mild boost up to 70 at max risk
        score = round(55.0 + blowout_risk * 15.0, 1)
        evidence.append(
            f"UNDER: blowout risk {blowout_risk:.0%} → mild boost "
            f"(starters may sit early)"
        )

    score = max(0.0, min(100.0, score))

    return FactorResult(
        name="Blowout Risk",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "blowout_risk": blowout_risk,
            "spread": spread,
            "h2h_avg_margin": h2h_avg_margin,
            "market_sensitivity": market_mult,
        },
        confidence=1.0,
    )
