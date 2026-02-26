"""
Factor 7: Blowout Risk (1%)
Uses the game spread + H2H margin history + team average win margin
to estimate how likely this game is to become a blowout.

Direction-aware:
  OVER:  high blowout risk = starters pulled early = stats cut short = BAD (low score)
  UNDER: high blowout risk = starters sit = harder to accumulate stats = GOOD (high score)
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import config
from src.models import FactorResult
from src.api.nba_stats import get_team_avg_win_margin

# Markets where blowout has limited impact (free throws, specific shot types)
_NON_COUNTING_MARKETS = {"player_threes", "player_blocks", "player_steals"}
# These are less affected by game pace/blowout than minutes-dependent stats


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
    """
    spread: absolute value of the point spread (e.g. 12.5 for OKC -12.5).
            None if unavailable.
    h2h_avg_margin: team's average margin in H2H games vs tonight's opponent.
    player_team_is_favorite: True if the player's team is favoured.
    player_is_starter: False = bench player → heavier penalty.
    market: prop market key (e.g. "player_points").
    """
    if season is None:
        season = config.DEFAULT_SEASON
    weight = config.FACTOR_WEIGHTS["blowout_risk"]

    evidence: list[str] = []

    # --- Early return when no data is available to assess risk ---
    if spread is None and h2h_avg_margin == 0:
        return FactorResult(
            name="Blowout Risk",
            score=50.0,
            weight=weight,
            evidence=["Spread unavailable — blowout risk unknown, using neutral score"],
            data={"blowout_risk": None, "spread": None, "h2h_avg_margin": 0, "penalty_applied": False},
            confidence=0.0,
        )

    # --- Blowout risk calculation ---
    spread_abs = abs(spread) if spread is not None else 0.0
    spread_risk = min(1.0, spread_abs / config.BLOWOUT_SPREAD_NORMALISER)

    h2h_risk = min(1.0, abs(h2h_avg_margin) / config.BLOWOUT_SPREAD_NORMALISER)

    # Team's avg win margin (dominant teams tend to blow teams out)
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
        evidence.append(f"Spread: {spread:+.1f} → spread risk: {spread_risk:.0%}")
    else:
        evidence.append("Spread unavailable — using H2H and team style only")

    evidence.append(f"H2H avg margin: {h2h_avg_margin:+.1f} → H2H risk: {h2h_risk:.0%}")
    evidence.append(f"Combined blowout risk: {blowout_risk:.0%}")

    # --- Convert blowout risk into a score penalty ---
    # score of 100 = no blowout risk; score goes down as risk goes up
    is_non_counting = market in _NON_COUNTING_MARKETS

    if blowout_risk > config.BLOWOUT_RISK_CUTOFF:
        if is_non_counting:
            penalty = config.BLOWOUT_PENALTY_NON_COUNTING
        elif not player_is_starter:
            penalty = config.BLOWOUT_PENALTY_BENCH
        elif player_team_is_favorite:
            penalty = config.BLOWOUT_PENALTY_FAVORITE_STAR
        else:
            penalty = config.BLOWOUT_PENALTY_UNDERDOG_STAR

        score = round((1.0 - penalty) * 100, 1)
        evidence.append(
            f"⚠️  High blowout risk ({blowout_risk:.0%}) — "
            f"{'non-counting' if is_non_counting else 'starter' if player_is_starter else 'bench'} "
            f"penalty: -{penalty:.0%}"
        )
    else:
        score = round((1.0 - blowout_risk * 0.3) * 100, 1)  # Mild penalty at low risk
        evidence.append(f"Blowout risk within acceptable range ({blowout_risk:.0%})")

    # For UNDER: use blowout_risk directly — 50 is neutral (no risk), scores up with risk.
    # A simple inversion (100 - over_score) would make the neutral baseline 0, which is wrong.
    # Instead: neutral (risk=0) → 50, maximum risk (risk=1.0) → 90
    if side == "under":
        score = round(min(100.0, 50.0 + blowout_risk * 40.0), 1)
        evidence.append(
            f"UNDER: blowout risk {blowout_risk:.0%} → favours UNDER "
            f"(starters may sit early, fewer stats)"
        )

    return FactorResult(
        name="Blowout Risk",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "blowout_risk": blowout_risk,
            "spread": spread,
            "h2h_avg_margin": h2h_avg_margin,
            "penalty_applied": blowout_risk > config.BLOWOUT_RISK_CUTOFF,
        },
        confidence=1.0,
    )
