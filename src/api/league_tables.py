"""
League-wide stat tables for the hit-probability model — one call per table,
covering every player/team. research/hit_model/snapshots.py fetches the same
tables as of past dates for training, so live and training inputs match.
"""
from __future__ import annotations

import time
from datetime import date

import pandas as pd
from nba_api.stats.endpoints import (
    LeagueDashOppPtShot, LeagueDashPlayerStats, LeagueDashPtStats, LeagueDashTeamStats, LeagueGameLog,
)

# name → (endpoint, params, index column)
TABLES = {
    "cs":    (LeagueDashPtStats, dict(pt_measure_type="CatchShoot", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "pu":    (LeagueDashPtStats, dict(pt_measure_type="PullUpShot", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "reb":   (LeagueDashPtStats, dict(pt_measure_type="Rebounding", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "pass":  (LeagueDashPtStats, dict(pt_measure_type="Passing", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "drive": (LeagueDashPtStats, dict(pt_measure_type="Drives", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "poss":  (LeagueDashPtStats, dict(pt_measure_type="Possessions", player_or_team="Player", per_mode_simple="PerGame"), "PLAYER_ID"),
    "padv":  (LeagueDashPlayerStats, dict(measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame"), "PLAYER_ID"),
    "tbase": (LeagueDashTeamStats, dict(measure_type_detailed_defense="Base", per_mode_detailed="PerGame"), "TEAM_ABBREVIATION"),
    "tadv":  (LeagueDashTeamStats, dict(measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame"), "TEAM_ABBREVIATION"),
    "topp":  (LeagueDashTeamStats, dict(measure_type_detailed_defense="Opponent", per_mode_detailed="PerGame"), "TEAM_ABBREVIATION"),
    "ocs":   (LeagueDashOppPtShot, dict(general_range_nullable="Catch and Shoot", per_mode_simple="PerGame"), "TEAM_ABBREVIATION"),
    "opu":   (LeagueDashOppPtShot, dict(general_range_nullable="Pullups", per_mode_simple="PerGame"), "TEAM_ABBREVIATION"),
}


def _with_team_abbr(df: pd.DataFrame) -> pd.DataFrame:
    if "TEAM_ABBREVIATION" not in df.columns and "TEAM_ID" in df.columns:
        from nba_api.stats.static import teams
        abbr = {t["id"]: t["abbreviation"] for t in teams.get_teams()}
        df = df.assign(TEAM_ABBREVIATION=df.TEAM_ID.map(abbr))
    return df


def fetch_snapshot(season: str, through: str | None = None, timeout: int = 60) -> dict[str, pd.DataFrame]:
    """Every table for `season`, using games through `through` (YYYY-MM-DD; None = all so far)."""
    kw = {"season": season, "timeout": timeout}
    if through:
        kw["date_to_nullable"] = date.fromisoformat(through).strftime("%m/%d/%Y")
    out = {}
    for name, (endpoint, params, index) in TABLES.items():
        df = _with_team_abbr(endpoint(**params, **kw).get_data_frames()[0])
        out[name] = df.set_index(index)
    return out


# In-process memo: tables are needed for every graded prop. Successes are kept
# 3h; a failed fetch isn't retried for 10 minutes so a throttled
# stats.nba.com can't add timeouts to every prop.
_memo: dict[str, tuple[float, object]] = {}


def _memoised(key: str, fetch, ttl_ok: int = 3 * 3600, ttl_fail: int = 600):
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < (ttl_ok if hit[1] is not None else ttl_fail):
        return hit[1]
    try:
        value = fetch()
    except Exception as exc:
        print(f"[league_tables] {key} failed: {exc}")
        value = None
    _memo[key] = (time.time(), value)
    return value


def get_snapshot(season: str) -> dict[str, pd.DataFrame] | None:
    """Today's league tables for the hit model (all games so far this season)."""
    return _memoised(f"snapshot_{season}", lambda: fetch_snapshot(season))


def get_league_player_log(season: str) -> pd.DataFrame | None:
    """Every player-game this season in one call — used for teammates'/opponents' minutes."""
    def fetch():
        df = LeagueGameLog(season=season, season_type_all_star="Regular Season",
                           player_or_team_abbreviation="P", timeout=60).get_data_frames()[0]
        df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce").fillna(0.0)
        return df[df["MIN"] > 0]
    return _memoised(f"league_log_{season}", fetch)
