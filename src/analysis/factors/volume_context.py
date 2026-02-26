"""
Factor 9: Volume & Usage Context (9%)
Measures whether a player's volume (minutes, attempts, rate) supports hitting
or staying under their prop line.

Direction-aware:
  OVER  → high minutes + high usage = favourable (more opportunities to score)
  UNDER → low minutes + low usage = favourable (fewer opportunities to exceed line)

Three market-specific metrics:
  POINTS / combos with PTS  → FGA rate (field goal attempts per game)
  3PT market                → FG3A rate (3-point attempt rate)
  ASSISTS market            → AST per 36 minutes (normalised for playing time)
  REBOUNDS + other combos   → MPG-based only

Minutes trend (recent vs season) is included for all markets.
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from src.models import FactorResult

# Markets that benefit from FGA-based usage scoring
_FGA_MARKETS = {"player_points", "player_points_rebounds", "player_points_assists",
                "player_points_rebounds_assists"}
# 3-pointer attempt markets
_FG3A_MARKETS = {"player_threes"}
# Assist markets — use per-36 assist rate
_AST_MARKETS = {"player_assists", "player_points_assists", "player_rebounds_assists",
                "player_points_rebounds_assists"}


def compute(
    df: pd.DataFrame,
    stat_col: str,
    line: float,
    market: str,
    side: str = "over",
) -> FactorResult:
    """
    df: full current-season game log (raw, not context-filtered).
    stat_col: stat column name (e.g. "PTS", "AST", "FG3M").
    line: the prop line.
    market: market key (e.g. "player_points").
    """
    weight = config.FACTOR_WEIGHTS["volume_context"]

    if df.empty or "MIN" not in df.columns:
        return FactorResult(
            name="Volume & Usage",
            score=50.0,
            weight=weight,
            evidence=["No game log data — volume context unavailable"],
            data={},
            confidence=0.0,
        )

    evidence: list[str] = []

    # ── Component A: Minutes trend (40% of factor) ───────────────────────────
    recent_minutes = df["MIN"].head(5)
    recent_mpg = float(recent_minutes.mean()) if len(recent_minutes) >= 1 else 0.0
    season_mpg = float(df["MIN"].mean()) if len(df) >= 1 else 0.0

    # Score based on absolute recent MPG
    # ≥30 MPG → 100, 25 MPG → 75, 20 MPG → 50, 15 MPG → 25, <15 → 15
    mpg_score = max(15.0, min(100.0, (recent_mpg - 15.0) * 5.0))

    # Penalty for declining minutes trend
    declining = False
    if season_mpg > 0 and recent_mpg < season_mpg * 0.85:
        mpg_score *= 0.80
        declining = True

    mpg_trend = " ↓ (declining)" if declining else ""
    evidence.append(
        f"Recent MPG: {recent_mpg:.1f} (season avg: {season_mpg:.1f}){mpg_trend}"
    )

    # ── Component B: Usage / attempt rate (60% of factor) ───────────────────
    usage_score: float = mpg_score  # default: MPG-based for markets without specific metric

    if market in _FGA_MARKETS and "FGA" in df.columns:
        fga_recent = float(df["FGA"].head(10).mean())
        # 15 FGA → 80, 20 FGA → ~100, 10 FGA → ~53, 6 FGA → ~32
        usage_score = min(100.0, max(10.0, (fga_recent / 15.0) * 80.0))
        evidence.append(f"FGA rate (last 10 games): {fga_recent:.1f}/game")

    elif market in _FG3A_MARKETS and "FG3A" in df.columns:
        fg3a_recent = float(df["FG3A"].head(10).mean())
        # 6 three-attempts → 80, 9 → 100, 3 → 40
        usage_score = min(100.0, max(10.0, (fg3a_recent / 6.0) * 80.0))
        evidence.append(f"3PA rate (last 10 games): {fg3a_recent:.1f}/game")

    elif market in _AST_MARKETS and "AST" in df.columns:
        ast_recent = float(df["AST"].head(10).mean())
        min_recent = float(df["MIN"].head(10).mean())
        if min_recent > 0:
            ast_per36 = (ast_recent / min_recent) * 36.0
            # 8 AST/36 → 80, 12 → ~100, 4 → ~40
            usage_score = min(100.0, max(10.0, (ast_per36 / 8.0) * 80.0))
            evidence.append(
                f"AST per 36 min: {ast_per36:.1f} (recent avg {ast_recent:.1f} AST in {min_recent:.0f} MPG)"
            )
        else:
            evidence.append("AST rate unavailable (no minutes data)")

    # ── Final score (OVER direction) ─────────────────────────────────────────
    over_score = 0.40 * mpg_score + 0.60 * usage_score
    over_score = round(min(100.0, max(0.0, over_score)), 1)

    # For UNDER: invert — low volume / low minutes = GOOD (fewer chances to exceed line)
    if side == "under":
        score = round(100.0 - over_score, 1)
        evidence.append(
            f"Low volume favours UNDER — high minutes/usage would work against it"
        )
    else:
        score = over_score

    n_games = len(df)
    confidence = min(1.0, n_games / 10)

    return FactorResult(
        name="Volume & Usage",
        score=score,
        weight=weight,
        evidence=evidence,
        data={
            "recent_mpg": recent_mpg,
            "season_mpg": season_mpg,
            "mpg_score": round(mpg_score, 1),
            "usage_score": round(usage_score, 1),
            "side": side,
        },
        confidence=confidence,
    )
