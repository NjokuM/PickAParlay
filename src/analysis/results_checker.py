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

import re
import time
import sys
import os
import unicodedata

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
    get_dates_missing_actuals,
    get_graded_props_missing_actuals,
    set_graded_prop_actual,
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


def _parse_minutes(raw) -> float | None:
    """V3 minutes "31:07" (or "PT31M07.00S") → 31.12."""
    if raw in (None, ""):
        return None
    text = str(raw)
    try:
        if text.startswith("PT"):
            mins, _, rest = text[2:].partition("M")
            return round(float(mins or 0) + float(rest.rstrip("S") or 0) / 60, 2)
        mins, _, secs = text.partition(":")
        return round(float(mins) + float(secs or 0) / 60, 2)
    except ValueError:
        return None


def _norm_name(name: str) -> str:
    """
    Normalise a player name for matching OddsAPI names to NBA box scores:
    strip accents (Jokić → jokic) and punctuation (C.J. → cj, Jr. → jr).
    """
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[.'’]", "", name.lower())
    return " ".join(name.replace("-", " ").split())


# ---------------------------------------------------------------------------
# Box score fetching
# ---------------------------------------------------------------------------

def fetch_game_info_for_date(game_date: str) -> list[dict]:
    """
    Return game info dicts for the given date using ScoreboardV3.
    Each dict: {"game_id": str, "status_id": int}
    Status: 1 = not started, 2 = live, 3 = final.

    ScoreboardV2 is broken for the 2025-26 playoff season (returns 0 rows).
    ScoreboardV3 uses YYYY-MM-DD format and works for both regular season and playoffs.
    """
    from nba_api.stats.endpoints import ScoreboardV3

    # Normalise to YYYY-MM-DD (ScoreboardV3 format)
    if "/" in game_date:
        parts = game_date.split("/")
        # Assume MM/DD/YYYY → YYYY-MM-DD
        game_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"

    # stats.nba.com intermittently throttles/times out (especially from cloud
    # IPs) — retry with backoff rather than silently reporting "0 games".
    games_df = None
    for attempt in range(1, 4):
        time.sleep(config.NBA_API_SLEEP)
        try:
            board = ScoreboardV3(game_date=game_date, league_id="00")
            games_df = board.data_sets[1].get_data_frame()   # game_header
            break
        except Exception as exc:
            print(f"[results] ScoreboardV3 failed for {game_date} (attempt {attempt}/3): {exc}")
            if attempt < 3:
                time.sleep(10 * attempt)
    if games_df is None:
        return []

    games: list[dict] = []
    for _, row in games_df.iterrows():
        games.append({
            "game_id": str(row["gameId"]),
            "status_id": int(row.get("gameStatus", 1)),
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
        raw = None
        for attempt in range(1, 3):
            time.sleep(config.NBA_API_SLEEP)
            try:
                raw = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=gid).get_dict()
                break
            except Exception as exc:
                print(f"[results] Box score {gid} failed (attempt {attempt}/2): {exc}")
                if attempt < 2:
                    time.sleep(5)
        if raw is None:
            # Game may not have been played yet — skip and grade the rest
            continue
        box = raw.get("boxScoreTraditional", {})

        for team_key in ("homeTeam", "awayTeam"):
            for p in box.get(team_key, {}).get("players", []):
                first = p.get("firstName", "")
                last  = p.get("familyName", "")
                name  = _norm_name(f"{first} {last}")
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
                player_stats[name]["_minutes"] = _parse_minutes(stats.get("minutes"))

    return player_stats


# ---------------------------------------------------------------------------
# Per-leg grading
# ---------------------------------------------------------------------------

def actual_stat(
    player_name: str,
    market: str,
    player_stats: dict[str, dict[str, float]],
) -> tuple[float, float | None] | None:
    """
    (actual stat value, minutes played) for a player/market from box scores,
    or None if the player isn't in the box scores (DNP / name mismatch) or the
    market is unknown.
    """
    # Normalise _alternate suffix so alt-line legs resolve correctly
    market = config.get_base_market(market)

    pstats = player_stats.get(_norm_name(player_name))
    if pstats is None:
        return None  # No data — player didn't play or name mismatch

    if market in _MARKET_TO_V3:
        actual = pstats.get(_MARKET_TO_V3[market], 0.0)
    elif market in _COMBO_COMPONENTS:
        actual = sum(pstats.get(k, 0.0) for k in _COMBO_COMPONENTS[market])
    else:
        return None  # Unknown market — can't grade
    return actual, pstats.get("_minutes")


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
    found = actual_stat(player_name, market, player_stats)
    if found is None:
        return None
    actual = found[0]

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

        actual, minutes = actual_stat(gp["player_name"], gp["market"], player_stats)
        record_graded_prop_result(gp["id"], result, actual_value=actual, actual_minutes=minutes)
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


def backfill_actuals(date_from: str | None = None, date_to: str | None = None) -> dict:
    """
    Fill actual_value / actual_minutes for already-graded props that predate
    actuals being stored (box scores can always be re-fetched). Leaves
    leg_result untouched. Dates are YYYY-MM-DD, inclusive.
    """
    dates = [d for d in get_dates_missing_actuals()
             if (date_from is None or d >= date_from) and (date_to is None or d <= date_to)]
    filled = missing = 0
    for d in dates:
        props = get_graded_props_missing_actuals(d)
        if not props:
            continue
        player_stats = fetch_box_scores(d)
        for gp in props:
            found = actual_stat(gp["player_name"], gp["market"], player_stats)
            if found is None:
                missing += 1
                continue
            set_graded_prop_actual(gp["id"], found[0], found[1])
            filled += 1
        print(f"[backfill] {d}: {len(props)} props, {filled} filled so far")
    return {"dates": len(dates), "filled": filled, "not_found": missing}
