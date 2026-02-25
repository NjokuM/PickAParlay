"""
ESPN unofficial injury API fetcher.
Returns a list of InjuryReport objects for all active NBA players.
Cached for 45 minutes (injuries can change quickly).
"""
from __future__ import annotations

import requests

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from src.cache import get as cache_get, set as cache_set
from src.models import InjuryReport

_CACHE_KEY = "espn_injuries"

# ESPN status strings → normalised internal status
_STATUS_MAP = {
    "out":          "out",
    "doubtful":     "doubtful",
    "questionable": "questionable",
    "probable":     "probable",
    "day-to-day":   "questionable",
    "injured reserve": "out",
    "suspension":   "out",
}


def get_injury_report() -> list[InjuryReport]:
    """Fetch and return all current NBA injury reports."""
    cached = cache_get(_CACHE_KEY, config.CACHE_TTL["injuries"])
    if cached:
        return [InjuryReport(**r) for r in cached]

    try:
        resp = requests.get(config.ESPN_INJURY_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    reports: list[InjuryReport] = []
    for team_entry in data.get("injuries", []):
        team_name = team_entry.get("team", {}).get("abbreviation", "UNK")
        for player_entry in team_entry.get("injuries", []):
            player_name = (
                player_entry.get("athlete", {}).get("displayName", "")
            )
            raw_status = (
                player_entry.get("status", "").lower().strip()
            )
            status = _STATUS_MAP.get(raw_status, raw_status)
            if player_name and status:
                reports.append(
                    InjuryReport(
                        player_name=player_name,
                        team=team_name,
                        status=status,
                    )
                )

    cache_set(_CACHE_KEY, [r.__dict__ for r in reports])
    return reports


def get_player_status(player_name: str, reports: list[InjuryReport]) -> str | None:
    """
    Look up a player's injury status from the report list.
    Uses fuzzy matching. Returns None if not found (assumed healthy).
    """
    from thefuzz import process

    if not reports:
        return None

    names = [r.player_name for r in reports]
    match, score = process.extractOne(player_name, names)
    if score < 80:
        return None

    for r in reports:
        if r.player_name == match:
            return r.status
    return None


def get_team_injuries(team_abbr: str, reports: list[InjuryReport]) -> list[InjuryReport]:
    """Return all injury reports for a specific team."""
    return [r for r in reports if r.team.upper() == team_abbr.upper()]


def is_player_unavailable(status: str | None) -> bool:
    """True if player should be excluded from slips."""
    return status in ("out", "doubtful")


def injury_severity_score(status: str | None) -> float:
    """
    0.0 = confirmed out (maximum impact)
    1.0 = no injury / probable (no impact)
    """
    return {
        "out":          0.0,
        "doubtful":     0.1,
        "questionable": 0.5,
        "probable":     0.9,
        None:           1.0,
    }.get(status, 1.0)
