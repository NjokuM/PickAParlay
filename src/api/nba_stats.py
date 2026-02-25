"""
nba_api wrapper: tonight's games, player game logs, team stats, H2H records.

All calls are cached. nba_api calls are rate-limited with a sleep between them.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
from nba_api.stats.endpoints import (
    ScoreboardV2,
    PlayerGameLog,
    PlayerCareerStats,
    LeagueDashTeamStats,
    TeamGameLog,
    CommonPlayerInfo,
)
from nba_api.stats.static import players as nba_players_static
from nba_api.stats.static import teams as nba_teams_static

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from src.cache import get as cache_get, set as cache_set
from src.models import NBAGame


def _sleep() -> None:
    time.sleep(config.NBA_API_SLEEP)


# ---------------------------------------------------------------------------
# Static lookups
# ---------------------------------------------------------------------------

def get_player_id(name: str) -> int | None:
    """Fuzzy player name → nba_api player ID."""
    from thefuzz import process
    all_players = nba_players_static.get_players()
    names = [p["full_name"] for p in all_players]
    match, score = process.extractOne(name, names)
    if score < 75:
        return None
    for p in all_players:
        if p["full_name"] == match:
            return p["id"]
    return None


def get_team_abbreviation(team_name: str) -> str | None:
    """Partial team name → abbreviation (e.g. 'Lakers' → 'LAL')."""
    from thefuzz import process
    all_teams = nba_teams_static.get_teams()
    names = [t["full_name"] for t in all_teams]
    match, score = process.extractOne(team_name, names)
    if score < 70:
        return None
    for t in all_teams:
        if t["full_name"] == match:
            return t["abbreviation"]
    return None


def get_team_id(abbreviation: str) -> int | None:
    all_teams = nba_teams_static.get_teams()
    for t in all_teams:
        if t["abbreviation"].upper() == abbreviation.upper():
            return t["id"]
    return None


# ---------------------------------------------------------------------------
# Tonight's games
# ---------------------------------------------------------------------------

def get_todays_games() -> list[NBAGame]:
    """
    Return NBAGame objects for games that have NOT yet started
    (or start within TIP_OFF_BUFFER_MINUTES).
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache_key = f"games_{date_str}"
    cached = cache_get(cache_key, config.CACHE_TTL["games"])
    if cached:
        return [NBAGame(**g) for g in cached]

    _sleep()
    try:
        board = ScoreboardV2(game_date=date_str)
        games_df = board.game_header.get_data_frame()
    except Exception:
        return []

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(minutes=config.TIP_OFF_BUFFER_MINUTES)

    results: list[NBAGame] = []
    for _, row in games_df.iterrows():
        game_time_str = row.get("GAME_STATUS_TEXT", "")
        # nba_api returns game time in ET; we skip started games
        if _game_has_started(row, now_utc):
            continue

        home_team_id = int(row["HOME_TEAM_ID"])
        visitor_team_id = int(row["VISITOR_TEAM_ID"])

        home_abbr = _team_id_to_abbr(home_team_id)
        away_abbr = _team_id_to_abbr(visitor_team_id)

        game = NBAGame(
            game_id=str(row["GAME_ID"]),
            home_team=home_abbr or str(home_team_id),
            away_team=away_abbr or str(visitor_team_id),
            home_team_id=home_team_id,
            away_team_id=visitor_team_id,
            game_date=date_str,
            game_time_utc=str(row.get("GAME_DATE_EST", "")),
            odds_event_id="",
        )
        results.append(game)

    cache_set(cache_key, [g.__dict__ for g in results])
    return results


def _game_has_started(row: Any, now_utc: datetime) -> bool:
    """Return True if game is in progress or already finished."""
    status = str(row.get("GAME_STATUS_ID", "1"))
    # 1 = not started, 2 = in progress, 3 = final
    return status in ("2", "3")


def _team_id_to_abbr(team_id: int) -> str | None:
    all_teams = nba_teams_static.get_teams()
    for t in all_teams:
        if t["id"] == team_id:
            return t["abbreviation"]
    return None


# ---------------------------------------------------------------------------
# Player game logs
# ---------------------------------------------------------------------------

def get_player_game_log(
    player_id: int,
    season: str | None = None,
    season_type: str = "Regular Season",
) -> pd.DataFrame:
    """Return player game log as a DataFrame. Cached 24h."""
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"gamelog_{player_id}_{season}_{season_type}"
    cached = cache_get(cache_key, config.CACHE_TTL["game_log"])
    if cached:
        return pd.DataFrame(cached)

    _sleep()
    try:
        log = PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )
        df = log.player_game_log.get_data_frame()
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    df = _add_computed_stats(df)
    df = _flag_overtime_games(df)
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
    df = df.sort_values("GAME_DATE", ascending=False).reset_index(drop=True)

    cache_set(cache_key, df.to_dict(orient="records"))
    return df


def get_player_game_log_prev_season(
    player_id: int,
    season: str | None = None,
) -> pd.DataFrame:
    if season is None:
        season = config.PREV_SEASON
    return get_player_game_log(player_id, season=season)


def _add_computed_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Add combo stat columns used by multi-stat prop markets."""
    if {"PTS", "REB", "AST"}.issubset(df.columns):
        df["PRA"] = df["PTS"] + df["REB"] + df["AST"]
        df["PR"]  = df["PTS"] + df["REB"]
        df["PA"]  = df["PTS"] + df["AST"]
        df["RA"]  = df["REB"] + df["AST"]
    return df


def _flag_overtime_games(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add IS_OT column. nba_api doesn't expose a direct OT flag but
    MIN (minutes played) > 40 is a reasonable proxy for OT involvement.
    """
    if "MIN" in df.columns:
        df["IS_OT"] = df["MIN"].apply(_parse_minutes) > 40
    else:
        df["IS_OT"] = False
    return df


def _parse_minutes(val: Any) -> float:
    """Parse "38:22" or 38.0 → float minutes."""
    try:
        if isinstance(val, str) and ":" in val:
            parts = val.split(":")
            return float(parts[0]) + float(parts[1]) / 60
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Player season averages
# ---------------------------------------------------------------------------

def get_player_season_averages(player_id: int, season: str | None = None) -> dict | None:
    """Return per-game season averages dict for key stats."""
    if season is None:
        season = config.DEFAULT_SEASON
    df = get_player_game_log(player_id, season=season)
    if df.empty or len(df) < config.MIN_GAMES_PLAYED:
        return None

    stat_cols = ["PTS", "AST", "REB", "FG3M", "BLK", "STL", "TOV",
                 "PRA", "PR", "PA", "RA"]
    avgs = {}
    for col in stat_cols:
        if col in df.columns:
            avgs[col] = round(df[col].mean(), 2)
    avgs["GP"] = len(df)
    return avgs


# ---------------------------------------------------------------------------
# Team stats / pace
# ---------------------------------------------------------------------------

def get_team_stats(season: str | None = None) -> pd.DataFrame:
    """League-wide team stats including pace. Cached 24h."""
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"team_stats_{season}"
    cached = cache_get(cache_key, config.CACHE_TTL["team_stats"])
    if cached:
        return pd.DataFrame(cached)

    _sleep()
    try:
        stats = LeagueDashTeamStats(
            season=season,
            per_mode_simple="PerGame",
        )
        df = stats.league_dash_team_stats.get_data_frame()
    except Exception:
        return pd.DataFrame()

    cache_set(cache_key, df.to_dict(orient="records"))
    return df


def get_team_pace_rank(team_id: int, season: str | None = None) -> tuple[float, int] | None:
    """Return (pace_value, pace_rank) for a team. Rank 1 = fastest."""
    if season is None:
        season = config.DEFAULT_SEASON
    df = get_team_stats(season)
    if df.empty or "TEAM_ID" not in df.columns:
        return None

    row = df[df["TEAM_ID"] == team_id]
    if row.empty:
        return None

    pace = float(row.iloc[0].get("PACE", 0))
    df_sorted = df.sort_values("PACE", ascending=False).reset_index(drop=True)
    rank = int(df_sorted[df_sorted["TEAM_ID"] == team_id].index[0]) + 1
    return pace, rank


def _get_raw_team_game_log(team_id: int, season: str | None = None) -> pd.DataFrame:
    """
    Shared cached TeamGameLog fetch.
    get_team_recent_form, get_h2h_record, and get_team_avg_win_margin all use
    this helper so each team's season log is only fetched ONCE per run,
    regardless of how many times downstream functions are called.
    """
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"raw_team_log_{team_id}_{season}"
    cached = cache_get(cache_key, config.CACHE_TTL["game_log"])
    if cached:
        return pd.DataFrame(cached)

    _sleep()
    try:
        tgl = TeamGameLog(team_id=team_id, season=season)
        df = tgl.team_game_log.get_data_frame()
    except Exception:
        return pd.DataFrame()

    cache_set(cache_key, df.to_dict(orient="records"))
    return df


def get_team_recent_form(team_id: int, season: str | None = None, last_n: int = 5) -> dict:
    """Return recent W/L record and back-to-back flag."""
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"team_form_{team_id}_{season}"
    cached = cache_get(cache_key, config.CACHE_TTL["game_log"])
    # Guard: only return cached value if it's the processed dict (not old raw-records list)
    if isinstance(cached, dict):
        return cached

    df = _get_raw_team_game_log(team_id, season)

    if df.empty:
        result = {"wins": 0, "losses": 0, "streak": "N/A", "back_to_back": False}
        cache_set(cache_key, result)
        return result

    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
    df = df.sort_values("GAME_DATE", ascending=False).reset_index(drop=True)

    recent = df.head(last_n)
    wins = int((recent["WL"] == "W").sum())
    losses = int((recent["WL"] == "L").sum())

    # Back-to-back: last two game dates are consecutive calendar days
    b2b = False
    if len(df) >= 2:
        d0 = df.iloc[0]["GAME_DATE"]
        d1 = df.iloc[1]["GAME_DATE"]
        b2b = (d0 - d1).days == 1

    # Streak
    streak = _compute_streak(df["WL"].tolist())

    result = {"wins": wins, "losses": losses, "streak": streak, "back_to_back": b2b}
    cache_set(cache_key, result)
    return result


def _compute_streak(wl_list: list[str]) -> str:
    if not wl_list:
        return "N/A"
    current = wl_list[0]
    count = 1
    for r in wl_list[1:]:
        if r == current:
            count += 1
        else:
            break
    return f"W{count}" if current == "W" else f"L{count}"


# ---------------------------------------------------------------------------
# Head-to-head team records
# ---------------------------------------------------------------------------

def get_h2h_record(team_id: int, opponent_abbr: str, season: str | None = None) -> dict:
    """
    Return W/L record and average margin for team_id vs opponent this season.
    Also fetches last season for a broader sample.
    """
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"h2h_{team_id}_{opponent_abbr}_{season}"
    cached = cache_get(cache_key, config.CACHE_TTL["h2h"])
    if cached:
        return cached

    # Use shared team log — avoids a duplicate TeamGameLog API call
    df = _get_raw_team_game_log(team_id, season)

    if df.empty:
        return {"wins": 0, "losses": 0, "avg_margin": 0, "games": 0}

    mask = df["MATCHUP"].str.contains(opponent_abbr, case=False, na=False)
    h2h = df[mask]

    if h2h.empty:
        result = {"wins": 0, "losses": 0, "avg_margin": 0, "games": 0}
    else:
        wins   = int((h2h["WL"] == "W").sum())
        losses = int((h2h["WL"] == "L").sum())
        margin = float(h2h["PLUS_MINUS"].mean()) if "PLUS_MINUS" in h2h.columns else 0.0
        result = {
            "wins":       wins,
            "losses":     losses,
            "avg_margin": round(margin, 1),
            "games":      len(h2h),
        }

    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Average winning margin (for blowout risk calculation)
# ---------------------------------------------------------------------------

def get_team_avg_win_margin(team_id: int, season: str | None = None) -> float:
    """Average point margin on wins only — indicates how dominant a team is."""
    if season is None:
        season = config.DEFAULT_SEASON
    cache_key = f"win_margin_{team_id}_{season}"
    cached = cache_get(cache_key, config.CACHE_TTL["team_stats"])
    if cached is not None:
        return float(cached)

    # Use shared team log — avoids a duplicate TeamGameLog API call
    df = _get_raw_team_game_log(team_id, season)

    if df.empty or "PLUS_MINUS" not in df.columns:
        return 0.0

    wins = df[df["WL"] == "W"]
    if wins.empty:
        return 0.0

    margin = float(wins["PLUS_MINUS"].mean())
    cache_set(cache_key, margin)
    return round(margin, 1)


# ---------------------------------------------------------------------------
# Current player team (authoritative roster lookup)
# ---------------------------------------------------------------------------

def get_player_current_team(player_id: int) -> str | None:
    """
    Return the player's current team abbreviation from the NBA API.

    Uses CommonPlayerInfo which always reflects the current roster assignment,
    regardless of trade date.  Cached for 12h so same-day trades are caught
    on the next refresh without hammering the API.

    Returns None if the player is not on an active roster (free agent, G-League,
    international) or if the request fails.
    """
    cache_key = f"player_team_{player_id}"
    cached = cache_get(cache_key, config.CACHE_TTL["player_team"])
    if cached:
        return str(cached)

    _sleep()
    try:
        info = CommonPlayerInfo(player_id=player_id).get_normalized_dict()
        row = info.get("CommonPlayerInfo", [{}])[0]
        abbr = str(row.get("TEAM_ABBREVIATION", "")).upper().strip()
        if abbr and abbr not in ("", "0"):
            cache_set(cache_key, abbr)
            return abbr
    except Exception:
        pass
    return None
