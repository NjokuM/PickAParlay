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
from src.database import (
    get_unresolved_graded_props,
    get_unresolved_legs,
    record_graded_prop_result,
    record_leg_result,
    propagate_results_to_slip_legs,
    auto_resolve_slip_outcome,
)


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

def fetch_game_info_for_date(game_date: str) -> list[dict]:
    """
    Return game info dicts for the given date.
    Each dict: {"game_id": str, "status_id": int}
    Status: 1 = not started, 2 = in progress, 3 = final.
    """
    from nba_api.stats.endpoints import scoreboardv2

    # ScoreboardV2 wants MM/DD/YYYY format
    if "-" in game_date:
        parts = game_date.split("-")
        date_fmt = f"{parts[1]}/{parts[2]}/{parts[0]}"
    else:
        date_fmt = game_date

    time.sleep(config.NBA_API_SLEEP)
    try:
        raw = scoreboardv2.ScoreboardV2(game_date=date_fmt).get_dict()
    except Exception:
        return []   # API failure — return empty rather than crash

    games: list[dict] = []
    for rs in raw.get("resultSets", []):
        if rs["name"] == "GameHeader":
            try:
                gid_idx = rs["headers"].index("GAME_ID")
                status_idx = rs["headers"].index("GAME_STATUS_ID")
            except ValueError:
                continue
            for row in rs["rowSet"]:
                games.append({
                    "game_id": row[gid_idx],
                    "status_id": int(row[status_idx]),
                })
    return games


def fetch_game_ids_for_date(game_date: str) -> list[str]:
    """Return a list of NBA game IDs for the given date (backwards compat)."""
    return [g["game_id"] for g in fetch_game_info_for_date(game_date)]


def fetch_box_scores(
    game_date: str,
    only_game_ids: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """
    Fetch all player box scores for every game on game_date.
    If only_game_ids is provided, only fetch those games (skip others).
    Returns {player_name_lower: {v3_stat_key: value, ...}}.
    """
    from nba_api.stats.endpoints import boxscoretraditionalv3

    if only_game_ids is None:
        only_game_ids = fetch_game_ids_for_date(game_date)
    player_stats: dict[str, dict[str, float]] = {}

    for gid in only_game_ids:
        time.sleep(config.NBA_API_SLEEP)
        try:
            raw = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=gid).get_dict()
        except Exception:
            # Game may not have been played yet — skip and grade the rest
            continue
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
    # Normalise _alternate suffix so alt-line legs resolve correctly
    market = config.get_base_market(market)

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
    Fetch box scores for game_date, then:
      1. Grade all unresolved graded_props rows (the primary source of truth)
      2. Propagate results to matching slip_legs rows
      3. Auto-resolve any slips where all legs are now graded

    Only grades props for FINISHED games (status 3). In-progress games are
    skipped — their props stay unresolved until the next check-results run.

    Returns a summary dict:
      {checked, hit, miss, no_data, slips_resolved, props_checked,
       games_finished, games_in_progress, games_not_started}
    """
    # For past dates, skip status check — ScoreboardV2 returns unreliable
    # statuses for historical dates (often shows "not started" for finished
    # games). Only check statuses for today's ET date where games may be live.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    if game_date < today_et:
        # Historical date — all games are finished, fetch all box scores
        all_game_ids = fetch_game_ids_for_date(game_date)
        print(f"[results] 📅 Historical date {game_date} — fetching all {len(all_game_ids)} game(s)")
        player_stats = fetch_box_scores(game_date, only_game_ids=all_game_ids)
        in_progress = []
        not_started = []
        finished_ids = all_game_ids
    else:
        # Today — check live statuses to avoid grading in-progress games
        game_info = fetch_game_info_for_date(game_date)
        finished_ids = [g["game_id"] for g in game_info if g["status_id"] == 3]
        in_progress = [g for g in game_info if g["status_id"] == 2]
        not_started = [g for g in game_info if g["status_id"] == 1]

        if in_progress:
            print(f"[results] ⚠️ {len(in_progress)} game(s) still in progress — skipping those")
        if not_started:
            print(f"[results] ⏳ {len(not_started)} game(s) not started yet")
        print(f"[results] ✅ Grading results for {len(finished_ids)} finished game(s)")

        player_stats = fetch_box_scores(game_date, only_game_ids=finished_ids)

    # ── Phase 1: Grade all unresolved graded_props ───────────────────────
    graded_props = get_unresolved_graded_props(game_date)

    props_checked = 0
    props_hit     = 0
    props_miss    = 0
    props_no_data = 0

    for gp in graded_props:
        result = check_leg(
            player_name=gp["player_name"],
            market=gp["market"],
            line=float(gp["line"]),
            side=(gp["side"] or "over").lower(),
            player_stats=player_stats,
        )

        if result is None:
            props_no_data += 1
            continue

        record_graded_prop_result(gp["id"], result)
        props_checked += 1
        if result == "HIT":
            props_hit += 1
        else:
            props_miss += 1

    # ── Phase 2: Propagate results to slip_legs ──────────────────────────
    legs_updated = propagate_results_to_slip_legs(game_date)

    # ── Phase 3: Also check any slip_legs without a matching graded_prop ─
    # (for slips saved before Phase 7 that have no graded_props row)
    legacy_legs = get_unresolved_legs(game_date)
    legacy_checked = 0
    legacy_no_data = 0

    for leg in legacy_legs:
        result = check_leg(
            player_name=leg["player_name"],
            market=leg["market"],
            line=float(leg["line"]),
            side=(leg["side"] or "over").lower(),
            player_stats=player_stats,
        )
        if result is None:
            legacy_no_data += 1
            continue
        record_leg_result(leg["id"], result)
        legacy_checked += 1

    # ── Phase 4: Auto-resolve slips ──────────────────────────────────────
    slips_resolved: set[int] = set()
    # Collect all slip_ids that might have been updated
    slip_ids_to_check: set[int] = set()
    for leg in legacy_legs:
        slip_ids_to_check.add(leg["slip_id"])
    # Also check slips that were updated via propagation
    from src.database import _connect
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT slip_id FROM slip_legs
               WHERE game_date = ? AND leg_result IS NOT NULL""",
            (game_date,),
        ).fetchall()
        for r in rows:
            slip_ids_to_check.add(r[0])

    for sid in slip_ids_to_check:
        resolved = auto_resolve_slip_outcome(sid)
        if resolved:
            slips_resolved.add(sid)

    return {
        "checked":        props_checked + legacy_checked,
        "hit":            props_hit,
        "miss":           props_miss,
        "no_data":        props_no_data + legacy_no_data,
        "slips_resolved": len(slips_resolved),
        "props_checked":  props_checked,
        "legs_propagated": legs_updated,
        "games_finished":    len(finished_ids),
        "games_in_progress": len(in_progress),
        "games_not_started": len(not_started),
    }
