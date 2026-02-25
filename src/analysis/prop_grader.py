"""
Prop grader — orchestrates all factor analysis for a single PlayerProp.
Fetches all required data, runs each factor, combines into a ValuedProp.
"""
from __future__ import annotations

import pandas as pd

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.models import PlayerProp, ValuedProp, FactorResult, InjuryReport
from src.api.nba_stats import (
    get_player_game_log,
    get_h2h_record,
    get_team_recent_form,
)
from src.api.odds_api import get_game_spread
from src.analysis.context_filter import apply_context_weights
from src.analysis.factors import (
    consistency,
    vs_opponent,
    home_away,
    injury_context,
    team_context,
    season_avg,
    blowout_risk,
)
from src.analysis.scorer import compute_value_score, label_recommendation, detect_suspicious_line


def grade_prop(
    prop: PlayerProp,
    injury_reports: list[InjuryReport],
    season: str = "2024-25",
) -> ValuedProp | None:
    """
    Run full multi-factor analysis on a single prop.
    Returns None if the player should be avoided entirely (injured OUT/DOUBTFUL).
    """
    game = prop.game
    market_cfg = config.MARKET_MAP.get(prop.market)
    if not market_cfg:
        return None

    # stat_col: for simple markets (compute is a string like "PTS") use compute directly;
    # for combo markets (compute is a lambda) use stat_key (e.g. "PRA" pre-computed column)
    compute_fn = market_cfg["compute"]
    stat_col = market_cfg["stat_key"] if callable(compute_fn) else compute_fn

    # --- Fetch game log FIRST so we can exit early before any team API calls ---
    df_raw = get_player_game_log(prop.nba_player_id, season=season)
    if df_raw.empty or len(df_raw) < config.MIN_GAMES_PLAYED:
        return None

    # --- Determine game context (extract team from already-fetched log) ---
    player_team_abbr = _get_player_team(prop, game, df=df_raw)
    tonight_is_home = player_team_abbr.upper() == game.home_team.upper()
    opponent_abbr = game.away_team if tonight_is_home else game.home_team

    # Back-to-back check
    form = get_team_recent_form(
        game.home_team_id if tonight_is_home else game.away_team_id,
        season=season,
    )
    tonight_is_b2b = form.get("back_to_back", False)

    # --- Apply context weights for location/team/B2B ---
    df_ctx = apply_context_weights(
        df_raw,
        current_team_abbr=player_team_abbr,
        tonight_is_b2b=tonight_is_b2b,
        current_season=season,
    )

    # --- Factor 1: Consistency ---
    f_consistency = consistency.compute(df_ctx, stat_col, prop.line)

    # --- Factor 2: vs Opponent ---
    h2h_team = get_h2h_record(
        game.home_team_id if tonight_is_home else game.away_team_id,
        opponent_abbr,
        season=season,
    )
    f_vs_opp = vs_opponent.compute(
        df_raw,           # Pass full log so filter_vs_opponent can slice it
        stat_col,
        prop.line,
        opponent_abbr,
        player_team_abbr,
        h2h_team_record=h2h_team,
    )

    # --- Factor 3: Home/Away ---
    f_home_away = home_away.compute(df_raw, stat_col, prop.line, tonight_is_home)

    # --- Factor 4: Injury Context ---
    f_injury = injury_context.compute(
        prop.player_name,
        player_team_abbr,
        opponent_abbr,
        prop.market,
        injury_reports,
    )

    # Bail early if player is unavailable
    if injury_context.should_avoid(f_injury):
        return None

    # --- Factor 5: Team Context ---
    team_id = game.home_team_id if tonight_is_home else game.away_team_id
    f_team = team_context.compute(team_id, player_team_abbr, season=season)

    # --- Factor 6: Season Average ---
    f_season = season_avg.compute(df_raw, stat_col, prop.line)

    # --- Factor 7: Blowout Risk ---
    spread = None
    if game.odds_event_id:
        spread = get_game_spread(game.odds_event_id)

    opponent_team_id = game.away_team_id if tonight_is_home else game.home_team_id
    player_team_is_fav = _team_is_favorite(spread, tonight_is_home)

    f_blowout = blowout_risk.compute(
        spread=spread,
        h2h_avg_margin=h2h_team.get("avg_margin", 0),
        player_team_is_favorite=player_team_is_fav,
        player_is_starter=True,  # assume starter; could be improved with lineup data
        market=prop.market,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        season=season,
    )

    # --- Line value factor (inline, 1%) ---
    f_line_value = _compute_line_value(f_consistency.data.get("floor", 0), prop.line)

    factors = [
        f_consistency,
        f_vs_opp,
        f_home_away,
        f_injury,
        f_team,
        f_season,
        f_blowout,
        f_line_value,
    ]

    value_score = compute_value_score(factors)
    recommendation = label_recommendation(value_score)

    # --- Suspicious line detection ---
    season_average = f_season.data.get("primary_avg")
    suspicious, suspicious_reason = detect_suspicious_line(prop.line, season_average)

    return ValuedProp(
        prop=prop,
        value_score=value_score,
        factors=factors,
        recommendation=recommendation,
        backing_data={
            "stat_col": stat_col,
            "season_avg": season_average,
            "opponent": opponent_abbr,
            "tonight_home": tonight_is_home,
            "b2b": tonight_is_b2b,
        },
        suspicious_line=suspicious,
        suspicious_reason=suspicious_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_player_team(prop: PlayerProp, game, df: pd.DataFrame | None = None) -> str:
    """
    Best-effort: the player's team abbreviation for tonight's game.

    Scans the game log from most-recent to oldest and returns the first entry
    where the player's team matches one of tonight's two teams.  This correctly
    handles mid-season transfers: a player who was just acquired may have a
    cached log full of games from their previous team.  Scanning finds the
    most-recent game they actually played FOR one of tonight's teams rather
    than blindly trusting df.iloc[0] (which could be a game with a third team).

    If no log entry matches either team (e.g. player joined today and the
    cached log is stale pre-trade), we fall back to game.home_team — callers
    should treat results for such players with lower confidence.

    Pass `df` (already-fetched game log) to avoid a duplicate API call.
    """
    if df is None:
        df = get_player_game_log(prop.nba_player_id)

    if not df.empty and "MATCHUP" in df.columns:
        home = game.home_team.upper()
        away = game.away_team.upper()

        for _, row in df.iterrows():
            matchup = str(row.get("MATCHUP", ""))
            for sep in (" vs. ", " @ "):
                if sep in matchup:
                    team = matchup.split(sep)[0].strip().upper()
                    if team in (home, away):
                        return team
                    break   # separator found but team is a third party; try next row

    # Could not determine team from log (stale cache, brand-new acquisition, etc.)
    return game.home_team


def _team_is_favorite(spread: float | None, player_is_home: bool) -> bool:
    """
    Spread is from the home team's perspective (negative = home favourite).
    """
    if spread is None:
        return True  # assume favourite if unknown
    if player_is_home:
        return spread < 0
    return spread > 0


def _compute_line_value(floor_value: float, line: float) -> FactorResult:
    """Inline line value factor (1%)."""
    weight = config.FACTOR_WEIGHTS["line_value"]
    if line <= 0 or floor_value <= 0:
        score = 50.0
        evidence = ["Line value: insufficient data"]
    else:
        score = min(100.0, (floor_value / line) * 50)
        evidence = [f"Floor ({floor_value:.1f}) / Line ({line}) → line value score: {score:.0f}"]

    return FactorResult(
        name="Line Value",
        score=round(score, 1),
        weight=weight,
        evidence=evidence,
        data={"floor": floor_value, "line": line},
        confidence=1.0,
    )
