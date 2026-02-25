"""
Shared context filter — used by every factor module before computing anything.

Applies context similarity weights to a player's game log:
  - Current team games weighted 1.0x
  - Previous team games weighted 0.15x (down-weighted after team transfer)
  - Back-to-back games filtered/weighted if tonight is a B2B

NOTE: Home/away filtering is intentionally NOT applied here — the consistency
factor needs all games (home + away). The home_away factor handles its own
location filtering internally.

Returns a DataFrame with a 'CTX_WEIGHT' column that downstream factors
multiply into their calculations.
"""
from __future__ import annotations

import pandas as pd

import config


def apply_context_weights(
    df: pd.DataFrame,
    current_team_abbr: str,
    tonight_is_b2b: bool,
    current_season: str = "2024-25",
) -> pd.DataFrame:
    """
    Main entry point. Given a full game log DataFrame, returns a copy
    with a CTX_WEIGHT column (float 0.0–1.0) applied to each row.

    Applies team-transfer weighting and B2B weighting only.
    Home/away filtering is handled per-factor, not here.
    """
    if df.empty:
        return df.copy()

    df = df.copy()

    # --- Team context ---
    df = _apply_team_weights(df, current_team_abbr, current_season)

    # --- Back-to-back context ---
    if tonight_is_b2b:
        df = _apply_b2b_weights(df)

    return df


def _team_from_matchup(matchup: str) -> str:
    """Extract the player's team abbreviation from a MATCHUP string.
    MATCHUP format: 'TOR vs. SAS' (home) or 'TOR @ SAS' (away).
    The first token is always the player's team.
    """
    for sep in (" vs. ", " @ "):
        if sep in matchup:
            return matchup.split(sep)[0].strip().upper()
    return matchup[:3].upper()


def _apply_team_weights(
    df: pd.DataFrame,
    current_team_abbr: str,
    current_season: str,
) -> pd.DataFrame:
    """
    Down-weight games from previous teams.
    Uses MATCHUP column (always present) instead of TEAM_ABBREVIATION (unreliable).
    If player has >= MIN_CURRENT_TEAM_GAMES, zero out previous team rows entirely.
    """
    if "MATCHUP" not in df.columns:
        df["CTX_WEIGHT"] = 1.0
        return df

    player_teams = df["MATCHUP"].apply(_team_from_matchup)
    current_mask = player_teams == current_team_abbr.upper()
    current_count = current_mask.sum()

    if "CTX_WEIGHT" not in df.columns:
        df["CTX_WEIGHT"] = 1.0

    if current_count >= config.MIN_CURRENT_TEAM_GAMES:
        # Enough current team data — zero out previous team games
        df.loc[~current_mask, "CTX_WEIGHT"] = 0.0
    else:
        # Mid-season trade scenario: keep previous team but at low weight
        df.loc[current_mask, "CTX_WEIGHT"] = config.CONTEXT_WEIGHTS["current_team"]
        df.loc[~current_mask, "CTX_WEIGHT"] = config.CONTEXT_WEIGHTS["previous_team"]

    return df


def _apply_home_away_weights(df: pd.DataFrame, tonight_is_home: bool) -> pd.DataFrame:
    """
    Zero out rows from the wrong location type.
    Home game → only keep rows where MATCHUP contains "vs."
    Away game → only keep rows where MATCHUP contains "@"
    """
    if "MATCHUP" not in df.columns:
        return df

    if tonight_is_home:
        # Home games have "vs." in matchup string
        location_mask = df["MATCHUP"].str.contains(r"\bvs\.", case=False, na=False)
    else:
        # Away games have " @ " in matchup string
        location_mask = df["MATCHUP"].str.contains(r"\s@\s", case=False, na=False)

    df.loc[~location_mask, "CTX_WEIGHT"] = 0.0
    return df


def _apply_b2b_weights(df: pd.DataFrame) -> pd.DataFrame:
    """
    When tonight is a back-to-back, down-weight non-B2B historical games.
    We detect B2B games by looking at consecutive game dates.
    """
    if "GAME_DATE" not in df.columns:
        return df

    df = df.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
    df = df.sort_values("GAME_DATE", ascending=False).reset_index(drop=True)

    # Mark each row as B2B or not based on gap to next game
    is_b2b = []
    dates = df["GAME_DATE"].tolist()
    for i, date in enumerate(dates):
        if i < len(dates) - 1:
            gap = abs((dates[i] - dates[i + 1]).days)
            is_b2b.append(gap == 1)
        else:
            is_b2b.append(False)

    df["IS_B2B_GAME"] = is_b2b

    # Down-weight non-B2B games when tonight is B2B
    b2b_mask = df["IS_B2B_GAME"]
    df.loc[b2b_mask, "CTX_WEIGHT"] = df.loc[b2b_mask, "CTX_WEIGHT"] * config.CONTEXT_WEIGHTS["b2b_tonight_b2b"]
    df.loc[~b2b_mask, "CTX_WEIGHT"] = df.loc[~b2b_mask, "CTX_WEIGHT"] * config.CONTEXT_WEIGHTS["normal_rest_b2b"]

    return df


# ---------------------------------------------------------------------------
# Opponent-specific context filter
# ---------------------------------------------------------------------------

def filter_vs_opponent(
    df: pd.DataFrame,
    opponent_abbr: str,
    current_team_abbr: str,
) -> pd.DataFrame:
    """
    Return rows where player faced tonight's opponent.
    Applies recency weighting:
      - Current season matchups: 1.0x
      - Last season matchups: 0.40x
      - Older: 0.05x

    Also excludes matchups where the player was on a different team
    (if current team data is sufficient).
    """
    if df.empty or "MATCHUP" not in df.columns:
        return df.copy()

    mask = df["MATCHUP"].str.contains(opponent_abbr, case=False, na=False)
    h2h = df[mask].copy()

    if h2h.empty:
        return h2h

    # Apply team context to H2H slice — use MATCHUP, not TEAM_ABBREVIATION
    player_teams = h2h["MATCHUP"].apply(_team_from_matchup)
    current_mask = player_teams == current_team_abbr.upper()
    current_count = current_mask.sum()

    if "CTX_WEIGHT" not in h2h.columns:
        h2h["CTX_WEIGHT"] = 1.0

    if current_count >= 2:
        h2h.loc[~current_mask, "CTX_WEIGHT"] *= 0.05  # prior team H2H almost irrelevant
    else:
        h2h.loc[~current_mask, "CTX_WEIGHT"] *= config.CONTEXT_WEIGHTS["previous_team"]

    # Season recency weighting
    if "SEASON_ID" in h2h.columns or "GAME_DATE" in h2h.columns:
        h2h = _apply_season_recency(h2h)

    return h2h


def _apply_season_recency(df: pd.DataFrame) -> pd.DataFrame:
    """Weight rows by how recent the season is."""
    if "GAME_DATE" not in df.columns:
        return df

    df = df.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
    max_date = df["GAME_DATE"].max()

    def season_weight(game_date: pd.Timestamp) -> float:
        days_ago = (max_date - game_date).days
        if days_ago <= 365:      # This season
            return config.CONTEXT_WEIGHTS["vs_opponent_current"]
        elif days_ago <= 730:    # Last season
            return config.CONTEXT_WEIGHTS["vs_opponent_last_szn"]
        else:
            return config.CONTEXT_WEIGHTS["vs_opponent_older"]

    df["CTX_WEIGHT"] = df["CTX_WEIGHT"] * df["GAME_DATE"].apply(season_weight)
    return df


# ---------------------------------------------------------------------------
# Confidence calculator
# ---------------------------------------------------------------------------

def compute_confidence(effective_sample: float, min_sample: int) -> float:
    """
    Returns a confidence multiplier 0.0–1.0.
    Below min_sample, the factor score is blended toward neutral (50).
    """
    return min(1.0, effective_sample / min_sample)


def effective_sample_size(df: pd.DataFrame) -> float:
    """
    Return the effective sample size accounting for CTX_WEIGHT.
    A row with weight 0.5 counts as 0.5 games.
    """
    if df.empty:
        return 0.0
    if "CTX_WEIGHT" in df.columns:
        return float(df["CTX_WEIGHT"].sum())
    return float(len(df))
