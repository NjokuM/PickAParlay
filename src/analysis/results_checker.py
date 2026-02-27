"""
Auto-result checker.

Fetches NBA box scores for a given game date and grades saved prop legs as
HIT / MISS by comparing the actual stat against the stored line + side.

Uses BoxScoreTraditionalV3 (V2 is deprecated for the 2025-26 season).
V3 structure:
  raw['boxScoreTraditional']['homeTeam']['players']  (list)
  raw['boxScoreTraditional']['awayTeam']['players']  (list)
  Each player dict:
    firstName, familyName
    statistics: {points, reboundsTotal, assists, threePointersMade,
                 blocksTotal, steals, turnovers, ...}

Combo markets (PRA, PR, PA, RA) are computed by summing component stats.
"""
from __future__ import annotations

import time
import sys
import os

# Ensure project root is on sys.path when this module is imported standalone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import config
from src.database import get_unresolved_legs, record_leg_result, auto_resolve_slip_outcome


# ---------------------------------------------------------------------------
# Stat-key mappings
# ---------------------------------------------------------------------------

# Maps OddsAPI market key → V3 statistics dict key (single-stat markets)
_MARKET_TO_V3: dict[str, str] = {
    "player_points":    "points",
    "player_assists":   "assists",
    "player_rebounds":  "reboundsTotal",
    "player_threes":    "threePointersMade",
    "player_blocks":    "blocksTotal",
    "player_steals":    "steals",
    "player_turnovers": "turnovers",
}

# All V3 stat keys we ever read — used to filter out non-numeric fields
# (e.g. minutes = "31:07") that would break float conversion.
_ALL_TRACKED_STATS: frozenset[str] = frozenset(
    list(_MARKET_TO_V3.values()) +
    [s for components in [
        ["points", "reboundsTotal", "assists"],
        ["points", "reboundsTotal"],
        ["points", "assists"],
        ["reboundsTotal", "assists"],
    ] for s in components]
)

# Maps combo market key → list of V3 stat keys to sum
_COMBO_COMPONENTS: dict[str, list[str]] = {
    "player_points_rebounds_assists": ["points", "reboundsTotal", "assists"],
    "player_points_rebounds":         ["points", "reboundsTotal"],
    "player_points_assists":          ["points", "assists"],
    "player_rebounds_assists":        ["reboundsTotal", "assists"],
}


# ---------------------------------------------------------------------------
# Box score fetching
# ---------------------------------------------------------------------------

def fetch_game_ids_for_date(game_date: str) -> list[str]:
    """
    Return a list of NBA game IDs for the given date ("YYYY-MM-DD" or "MM/DD/YYYY").
    Uses ScoreboardV2 which returns results for any past date.
    """
    from nba_api.stats.endpoints import scoreboardv2

    # ScoreboardV2 wants MM/DD/YYYY format
    if "-" in game_date:
        parts = game_date.split("-")
        date_fmt = f"{parts[1]}/{parts[2]}/{parts[0]}"
    else:
        date_fmt = game_date

    time.sleep(config.NBA_API_SLEEP)
    raw = scoreboardv2.ScoreboardV2(game_date=date_fmt).get_dict()

    game_ids: list[str] = []
    for rs in raw.get("resultSets", []):
        if rs["name"] == "GameHeader":
            gid_idx = rs["headers"].index("GAME_ID")
            for row in rs["rowSet"]:
                game_ids.append(row[gid_idx])
    return game_ids


def fetch_box_scores(game_date: str) -> dict[str, dict[str, float]]:
    """
    Fetch all player box scores for every game on game_date.
    Returns {player_name_lower: {v3_stat_key: value, ...}}.
    """
    from nba_api.stats.endpoints import boxscoretraditionalv3

    game_ids = fetch_game_ids_for_date(game_date)
    player_stats: dict[str, dict[str, float]] = {}

    for gid in game_ids:
        time.sleep(config.NBA_API_SLEEP)
        raw = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=gid).get_dict()
        box = raw.get("boxScoreTraditional", {})

        for team_key in ("homeTeam", "awayTeam"):
            for p in box.get(team_key, {}).get("players", []):
                first = p.get("firstName", "")
                last  = p.get("familyName", "")
                name  = f"{first} {last}".strip().lower()
                if not name:
                    continue
                stats = p.get("statistics", {})
                # Only extract numeric stat keys we actually use.
                # V3 also includes non-numeric fields like minutes ("31:07") which
                # cannot be cast to float — filtering by known keys avoids that error.
                player_stats[name] = {
                    k: float(v) if v is not None else 0.0
                    for k, v in stats.items()
                    if k in _ALL_TRACKED_STATS
                }

    return player_stats


# ---------------------------------------------------------------------------
# Per-leg grading
# ---------------------------------------------------------------------------

def check_leg(
    player_name: str,
    market: str,
    line: float,
    side: str,                             # "over" | "under"
    player_stats: dict[str, dict[str, float]],
) -> str | None:
    """
    Grade a single prop leg.
    Returns "HIT", "MISS", or None (player not in box scores — DNP / not found).
    """
    pstats = player_stats.get(player_name.lower())
    if pstats is None:
        return None  # No data — player didn't play or name mismatch

    # Compute the relevant stat value
    if market in _MARKET_TO_V3:
        v3_key = _MARKET_TO_V3[market]
        actual = pstats.get(v3_key, 0.0)
    elif market in _COMBO_COMPONENTS:
        keys   = _COMBO_COMPONENTS[market]
        actual = sum(pstats.get(k, 0.0) for k in keys)
    else:
        # Unknown market — can't grade
        return None

    if side == "over":
        return "HIT" if actual > line else "MISS"
    else:  # "under"
        return "HIT" if actual < line else "MISS"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_results_for_date(game_date: str) -> dict:
    """
    Fetch box scores for game_date, then grade all unresolved saved prop legs
    for that date.  Records HIT/MISS for each leg and auto-resolves slip
    WIN/LOSS once all legs are graded.

    Returns a summary dict:
      {checked, hit, miss, no_data, slips_resolved}
    """
    # Fetch box scores (may take a few seconds with per-request sleeps)
    player_stats = fetch_box_scores(game_date)

    # Pull all unresolved legs for this date
    legs = get_unresolved_legs(game_date)

    checked       = 0
    hit           = 0
    miss          = 0
    no_data       = 0
    slips_resolved: set[int] = set()

    for leg in legs:
        result = check_leg(
            player_name=leg["player_name"],
            market=leg["market"],
            line=float(leg["line"]),
            side=(leg["side"] or "over").lower(),
            player_stats=player_stats,
        )

        if result is None:
            no_data += 1
            continue

        record_leg_result(leg["id"], result)
        checked += 1
        if result == "HIT":
            hit += 1
        else:
            miss += 1

        # Try to auto-resolve the parent slip
        resolved = auto_resolve_slip_outcome(leg["slip_id"])
        if resolved:
            slips_resolved.add(leg["slip_id"])

    return {
        "checked":        checked,
        "hit":            hit,
        "miss":           miss,
        "no_data":        no_data,
        "slips_resolved": len(slips_resolved),
    }
