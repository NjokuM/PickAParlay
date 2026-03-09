"""
Factor 4: Injury Context (12%)
Scores the injury situation for the player and both teams.
  - Player themselves injured → score 0, flag AVOID
  - Teammate depth depletion → counts ALL injured teammates' cumulative
    minutes lost, with extra weight for high-usage stars on specific markets
  - Opponent depth depletion → weaker opposition benefits OVER, hurts UNDER
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

# Thresholds for high-usage (star) detection — used for market-specific bonuses
_HIGH_USAGE_MPG = 24.0    # starter-level minutes
_HIGH_USAGE_FGA = 12.0    # significant shot volume

# Default MPG estimate when a player isn't found in league stats
_DEFAULT_MPG = 15.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lookup_player_mpg(player_name: str, usage_data: dict) -> tuple[float, bool]:
    """
    Look up a player's MPG from league-wide usage data.
    Returns (mpg, is_star).
    Falls back to _DEFAULT_MPG if the player is not found.
    """
    pname = player_name.strip().lower()
    stats = usage_data.get(pname)
    if stats:
        mpg = stats["mpg"]
        is_star = mpg >= _HIGH_USAGE_MPG or stats.get("fga", 0) >= _HIGH_USAGE_FGA
        return mpg, is_star

    # Fuzzy match on last name
    last_name = pname.split()[-1] if pname else ""
    if last_name:
        for name, s in usage_data.items():
            if last_name in name:
                mpg = s["mpg"]
                is_star = mpg >= _HIGH_USAGE_MPG or s.get("fga", 0) >= _HIGH_USAGE_FGA
                return mpg, is_star

    return _DEFAULT_MPG, False


def _depth_depletion_impact(total_minutes_lost: float) -> float:
    """
    Convert cumulative minutes lost into a score impact (0–30).
    Scales non-linearly — losing 80+ minutes is a depth crisis.

      0–20 min  → up to  5 pts  (minor — one role player out)
     20–50 min  → up to 12 pts  (moderate — 2-3 players out)
     50–80 min  → up to 20 pts  (major — 3-4 rotation players)
     80+ min    → up to 30 pts  (extreme — team decimated)
    """
    if total_minutes_lost <= 0:
        return 0.0
    if total_minutes_lost < 20:
        impact = total_minutes_lost * 0.25
    elif total_minutes_lost < 50:
        impact = 5.0 + (total_minutes_lost - 20) * 0.233
    elif total_minutes_lost < 80:
        impact = 12.0 + (total_minutes_lost - 50) * 0.267
    else:
        impact = 20.0 + (total_minutes_lost - 80) * 0.25
    return min(30.0, impact)


# ---------------------------------------------------------------------------
# Main compute
# ---------------------------------------------------------------------------

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
            data={"player_status": player_status, "avoid": True, "depth_minutes_lost": 0.0},
            confidence=1.0,
        )

    evidence: list[str] = []
    score = 75.0  # baseline — player healthy, no relevant injuries

    if player_status:
        severity = injury_severity_score(player_status)
        if side == "under":
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

    # 2. Teammate injuries — depth depletion + star market bonuses
    teammate_injuries = get_team_injuries(player_team_abbr, injury_reports)
    teammate_impact, depth_minutes_lost = _assess_teammate_impact(
        player_name, market, teammate_injuries, evidence, side=side
    )
    score += teammate_impact

    # 3. Opponent injuries — depth depletion + star bonuses
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
            "depth_minutes_lost": depth_minutes_lost,
            "avoid": False,
        },
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Teammate impact — depth depletion + star market bonuses
# ---------------------------------------------------------------------------

def _assess_teammate_impact(
    player_name: str,
    market: str,
    teammate_injuries: list[InjuryReport],
    evidence: list[str],
    side: str = "over",
) -> tuple[float, float]:
    """
    Estimate how teammate injuries shift this player's expected stats.

    Two-tier scoring:
      1. Base depth depletion — counts ALL unavailable teammates' cumulative
         minutes lost.  More teammates out = more minutes/touches for survivors.
      2. Star market bonuses — high-usage teammates out get an extra bump on
         specific markets (points, assists) layered on top.

    Returns (score_impact, total_minutes_lost).
    total_minutes_lost is stored in FactorResult.data for downstream use
    by volume_context (injury-driven minutes boost).
    """
    usage_data = get_league_player_usage()
    total_minutes_lost = 0.0
    star_impact = 0.0
    injured_names: list[str] = []

    for inj in teammate_injuries:
        if inj.player_name.lower() == player_name.lower():
            continue  # the player themselves — skip
        if not is_player_unavailable(inj.status):
            continue  # questionable/probable — still expected to play

        mpg, is_star = _lookup_player_mpg(inj.player_name, usage_data)
        total_minutes_lost += mpg
        injured_names.append(f"{inj.player_name} ({inj.status}, ~{mpg:.0f} MPG)")

        # Star-specific market adjustments (layered on top of depth base)
        if is_star:
            if "assists" in market:
                if side == "under":
                    star_impact += 5
                else:
                    star_impact -= 5
            elif "points" in market:
                if side == "under":
                    star_impact -= 8
                else:
                    star_impact += 8

    # --- Base depth depletion score (applies to ALL markets) ---
    depth_impact = _depth_depletion_impact(total_minutes_lost)

    # Direction: OVER benefits from depth depletion (more mins/touches),
    #            UNDER is hurt by it (player will do MORE)
    if side == "over":
        total_impact = depth_impact + star_impact
    else:
        total_impact = -depth_impact + star_impact

    # Evidence
    n_out = len(injured_names)
    if n_out > 0:
        if n_out <= 3:
            for name_str in injured_names:
                evidence.append(f"Teammate out: {name_str}")
        else:
            # Summarise when many are out to avoid evidence spam
            evidence.append(
                f"⚠️ {n_out} teammates out (~{total_minutes_lost:.0f} combined MPG): "
                + ", ".join(injured_names)
            )
        severity_label = (
            "minor" if total_minutes_lost < 20 else
            "moderate" if total_minutes_lost < 50 else
            "major" if total_minutes_lost < 80 else
            "extreme depth crisis"
        )
        direction = "OVER" if side == "over" else "UNDER"
        evidence.append(
            f"Depth depletion: {severity_label} ({total_minutes_lost:.0f} min lost) "
            f"→ {'favours' if side == 'over' else 'works against'} {direction} "
            f"(impact: {'+' if total_impact >= 0 else ''}{total_impact:.0f})"
        )

    return total_impact, total_minutes_lost


# ---------------------------------------------------------------------------
# Opponent impact — depth depletion + star bonuses
# ---------------------------------------------------------------------------

def _assess_opponent_impact(
    market: str,
    opponent_injuries: list[InjuryReport],
    evidence: list[str],
    side: str = "over",
) -> float:
    """
    Opponent injuries weaken the opposition.
    Two-tier: base depletion + star bonuses for relevant markets.
    """
    usage_data = get_league_player_usage()
    total_opp_minutes_lost = 0.0
    star_impact = 0.0
    opp_injured_names: list[str] = []

    for inj in opponent_injuries:
        if not is_player_unavailable(inj.status):
            continue

        mpg, is_star = _lookup_player_mpg(inj.player_name, usage_data)
        total_opp_minutes_lost += mpg
        opp_injured_names.append(f"{inj.player_name} ({inj.status})")

        # Star-specific bonuses for scoring/rebounding/assist markets
        if is_star:
            is_relevant = (
                "points" in market or "rebounds" in market or
                "assists" in market or "pra" in market.lower()
            )
            if is_relevant:
                if side == "under":
                    star_impact -= 7
                else:
                    star_impact += 7

    # Base opponent depletion (team-wide weakness)
    base_opp_impact = 0.0
    if total_opp_minutes_lost >= 30:
        base_opp_impact = min(15.0, 5.0 + (total_opp_minutes_lost - 30) * 0.25)
        if side == "under":
            base_opp_impact = -base_opp_impact  # weaker opponent = more stats = BAD for UNDER

    total_impact = star_impact + base_opp_impact

    # Evidence
    n_out = len(opp_injured_names)
    if n_out > 0:
        if total_opp_minutes_lost >= 30:
            evidence.append(
                f"Opponent depleted: {n_out} players out (~{total_opp_minutes_lost:.0f} min) "
                f"→ {'weaker defence +' if side == 'over' else 'works against UNDER'}"
            )
        elif n_out > 0 and any(
            _lookup_player_mpg(inj.player_name, usage_data)[1]
            for inj in opponent_injuries if is_player_unavailable(inj.status)
        ):
            # At least one star out but total minutes not extreme
            for name_str in opp_injured_names[:2]:
                direction = "defence weakened +" if side == "over" else "weaker defence (works against UNDER)"
                evidence.append(f"Opponent {name_str} — {direction}")

    return total_impact


def should_avoid(factor: FactorResult) -> bool:
    return bool(factor.data.get("avoid", False))
