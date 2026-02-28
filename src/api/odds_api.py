"""
The Odds API wrapper.
Fetches game lines (spreads) and player props for tonight's NBA games.
Prefers Paddy Power; falls back to best available if PP doesn't offer a market.
API credit usage is tracked via src/cache.py.
"""
from __future__ import annotations

import requests
from typing import Any

import config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from src.cache import (
    get as cache_get,
    set as cache_set,
    record_api_request,
    sync_credits_from_header,
    get_credits_remaining,
)
from src.models import NBAGame, PlayerProp


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict) -> dict | list | None:
    """Make a GET request to The Odds API. Returns None on failure."""
    if not config.ODDS_API_KEY:
        return None
    params["apiKey"] = config.ODDS_API_KEY
    url = f"{config.ODDS_API_BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        # Sync credit counter directly from the API's ground-truth headers.
        # x-requests-used reflects actual billing (e.g. prop fetches cost per market),
        # so this is always more accurate than our manual +1 counting.
        raw_used = resp.headers.get("x-requests-used")
        raw_remaining = resp.headers.get("x-requests-remaining")
        if raw_used is not None:
            try:
                sync_credits_from_header(
                    used=int(raw_used),
                    remaining=int(raw_remaining) if raw_remaining is not None else None,
                )
            except ValueError:
                record_api_request(1)   # header malformed — fall back to +1
        else:
            record_api_request(1)       # no header at all — fall back to +1
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def _decimal_odds(price: float | None) -> float:
    """Ensure odds are in decimal format (The Odds API returns decimal)."""
    if price is None or price <= 0:
        return 0.0
    return round(float(price), 3)


def _best_odds_for_market(
    bookmakers: list[dict],
    market_key: str,
    player_name: str,
    side: str,
) -> tuple[float, str]:
    """
    Return (best_decimal_odds, bookmaker_name) across all bookmakers.
    side: "Over" or "Under"
    """
    best_odds = 0.0
    best_bookie = "unknown"
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if (
                    outcome.get("description", "").lower() == player_name.lower()
                    and outcome.get("name", "") == side
                ):
                    odds = _decimal_odds(outcome.get("price"))
                    if odds > best_odds:
                        best_odds = odds
                        best_bookie = bm["key"]
    return best_odds, best_bookie


def _paddy_odds_for_market(
    bookmakers: list[dict],
    market_key: str,
    player_name: str,
    side: str,
) -> float:
    """Return Paddy Power odds only. 0.0 if not available."""
    for bm in bookmakers:
        if bm["key"] != config.PREFERRED_BOOKMAKER:
            continue
        for market in bm.get("markets", []):
            if market["key"] != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if (
                    outcome.get("description", "").lower() == player_name.lower()
                    and outcome.get("name", "") == side
                ):
                    return _decimal_odds(outcome.get("price"))
    return 0.0


# ---------------------------------------------------------------------------
# Events (game IDs for The Odds API)
# ---------------------------------------------------------------------------

def get_events() -> list[dict]:
    """Fetch today's NBA events from The Odds API."""
    cache_key = "odds_events"
    cached = cache_get(cache_key, config.CACHE_TTL["props"])
    if cached is not None:
        return cached

    data = _get(
        f"/sports/{config.ODDS_SPORT}/events",
        {"regions": config.ODDS_REGIONS},
    )
    if not data:
        return []

    cache_set(cache_key, data)
    return data


def match_game_to_event(game: NBAGame, events: list[dict]) -> str | None:
    """
    Match an NBAGame to an Odds API event ID by team name fuzzy matching.
    Returns the event_id string or None.
    """
    from thefuzz import process

    if not events:
        return None

    home = game.home_team.lower()
    away = game.away_team.lower()

    for event in events:
        home_team = event.get("home_team", "").lower()
        away_team = event.get("away_team", "").lower()
        if (home in home_team or home_team in home) and (
            away in away_team or away_team in away
        ):
            return event["id"]

    # Fuzzy fallback
    all_matchups = [
        f"{e.get('away_team','')} @ {e.get('home_team','')}"
        for e in events
    ]
    target = f"{game.away_team} @ {game.home_team}"
    if all_matchups:
        match, score = process.extractOne(target, all_matchups)
        if score >= 70:
            idx = all_matchups.index(match)
            return events[idx]["id"]
    return None


# ---------------------------------------------------------------------------
# Game spreads (for blowout risk)
# ---------------------------------------------------------------------------

def get_game_spread(event_id: str) -> float | None:
    """
    Return the spread for the home team (negative = home favourite).
    Tries preferred bookmaker first, then falls back to any bookmaker
    in the configured region.  Returns None if truly unavailable.
    """
    cache_key = f"spread_{event_id}"
    cached = cache_get(cache_key, config.CACHE_TTL["props"])
    if cached is not None:
        return float(cached)

    # Try preferred bookmaker first
    data = _get(
        f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
        {
            "regions": config.ODDS_REGIONS,
            "markets": "spreads",
            "bookmakers": config.PREFERRED_BOOKMAKER,
        },
    )
    spread = _extract_spread(data.get("bookmakers", [])) if data else None

    # Fallback: any bookmaker in the region
    if spread is None:
        data = _get(
            f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
            {
                "regions": f"{config.ODDS_REGIONS},us",
                "markets": "spreads",
            },
        )
        spread = _extract_spread(data.get("bookmakers", [])) if data else None

    if spread is not None:
        cache_set(cache_key, spread)
    return spread


def _extract_spread(bookmakers: list[dict]) -> float | None:
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] != "spreads":
                continue
            for outcome in market.get("outcomes", []):
                point = outcome.get("point")
                if point is not None:
                    return float(point)
    return None


# ---------------------------------------------------------------------------
# Player props
# ---------------------------------------------------------------------------

def get_player_props_for_event(
    event_id: str,
    markets: list[str] | None = None,
) -> list[dict]:
    """
    Fetch all player prop outcomes for an event.
    Returns raw outcome dicts with player_name, market, line, over_odds, under_odds,
    bookmaker, is_paddy_power.
    """
    if markets is None:
        markets = list(config.MARKET_MAP.keys())

    cache_key = f"props_{event_id}_{'_'.join(sorted(markets))}"
    cached = cache_get(cache_key, config.CACHE_TTL["props"])
    if cached is not None:
        return cached

    markets_str = ",".join(markets)
    data = _get(
        f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
        {
            "regions": config.ODDS_REGIONS,
            "markets": markets_str,
        },
    )
    if not data:
        return []

    bookmakers = data.get("bookmakers", [])
    results = _extract_props(bookmakers, markets)

    cache_set(cache_key, results)
    return results


def _extract_props(bookmakers: list[dict], markets: list[str]) -> list[dict]:
    """
    Extract player props from bookmakers list.
    Prefers Paddy Power; falls back to best available line.
    Returns one entry per (player, market) — the best available.
    """
    # Index: (player_name, market) → {pp_over, pp_under, best_over, best_under, best_bookie}
    index: dict[tuple[str, str], dict] = {}

    for bm in bookmakers:
        bm_key = bm["key"]
        for market in bm.get("markets", []):
            mkt = market["key"]
            if mkt not in markets:
                continue

            # Group outcomes by player
            player_outcomes: dict[str, dict] = {}
            for outcome in market.get("outcomes", []):
                player = outcome.get("description", "")
                if not player:
                    continue
                side = outcome.get("name", "")
                point = outcome.get("point")
                price = _decimal_odds(outcome.get("price"))

                if player not in player_outcomes:
                    player_outcomes[player] = {"over": None, "under": None, "line": None}

                if side == "Over":
                    player_outcomes[player]["over"] = price
                    player_outcomes[player]["line"] = point
                elif side == "Under":
                    player_outcomes[player]["under"] = price

            for player, odds_data in player_outcomes.items():
                key = (player, mkt)
                if key not in index:
                    index[key] = {
                        "player_name": player,
                        "market": mkt,
                        "line": odds_data["line"],
                        "pp_over": 0.0,
                        "pp_under": 0.0,
                        "best_over": 0.0,
                        "best_under": 0.0,
                        "best_bookie": "",
                    }

                if bm_key == config.PREFERRED_BOOKMAKER:
                    index[key]["pp_over"]  = odds_data["over"] or 0.0
                    index[key]["pp_under"] = odds_data["under"] or 0.0
                    if odds_data["line"] is not None:
                        index[key]["line"] = odds_data["line"]

                over = odds_data["over"] or 0.0
                if over > index[key]["best_over"]:
                    index[key]["best_over"]   = over
                    index[key]["best_bookie"] = bm_key
                    if odds_data["line"] is not None and index[key]["line"] is None:
                        index[key]["line"] = odds_data["line"]

                under = odds_data["under"] or 0.0
                if under > index[key]["best_under"]:
                    index[key]["best_under"] = under

    # Flatten to list of prop dicts, choosing PP if available
    results = []
    for (player, mkt), d in index.items():
        if d["line"] is None:
            continue

        use_pp = d["pp_over"] > 0.0
        results.append({
            "player_name":      player,
            "market":           mkt,
            "line":             float(d["line"]),
            "over_odds":        d["pp_over"] if use_pp else d["best_over"],
            "under_odds":       d["pp_under"] if use_pp else d["best_under"],
            "bookmaker":        config.PREFERRED_BOOKMAKER if use_pp else d["best_bookie"],
            "is_paddy_power":   use_pp,
        })

    return results


# ---------------------------------------------------------------------------
# Alternate props (for Ladder Challenge)
# ---------------------------------------------------------------------------

def _extract_alternate_props(bookmakers: list[dict], markets: list[str]) -> list[dict]:
    """
    Like _extract_props but keys on (player, market, line) so each distinct
    threshold gets its own entry.  Only keeps entries where at least one side's
    odds falls in [ALTERNATE_ODDS_MIN, ALTERNATE_ODDS_MAX].
    """
    index: dict[tuple, dict] = {}

    for bm in bookmakers:
        bm_key = bm["key"]
        for market in bm.get("markets", []):
            mkt = market["key"]
            if mkt not in markets:
                continue
            for outcome in market.get("outcomes", []):
                player = outcome.get("description", "")
                if not player:
                    continue
                side  = outcome.get("name", "")
                point = outcome.get("point")
                price = _decimal_odds(outcome.get("price"))
                if point is None or price <= 0:
                    continue

                key = (player, mkt, float(point))
                if key not in index:
                    index[key] = {
                        "player_name": player,
                        "market":      mkt,
                        "line":        float(point),
                        "over_odds":   0.0,
                        "under_odds":  0.0,
                        "bookmaker":   bm_key,
                        "is_paddy_power": bm_key == config.PREFERRED_BOOKMAKER,
                        "is_alternate":   True,
                    }
                if side == "Over":
                    index[key]["over_odds"] = max(index[key]["over_odds"], price)
                elif side == "Under":
                    index[key]["under_odds"] = max(index[key]["under_odds"], price)

    # Filter to entries where at least one side is in the useful odds window
    results = []
    for d in index.values():
        over_ok  = config.ALTERNATE_ODDS_MIN <= d["over_odds"]  <= config.ALTERNATE_ODDS_MAX
        under_ok = config.ALTERNATE_ODDS_MIN <= d["under_odds"] <= config.ALTERNATE_ODDS_MAX
        if over_ok or under_ok:
            results.append(d)
    return results


def get_alternate_props_for_event(event_id: str) -> list[dict]:
    """
    Fetch alternate prop lines for a Ladder Challenge.
    Returns raw prop dicts (same shape as get_player_props_for_event output,
    but with is_alternate=True and one entry per distinct line threshold).
    """
    cache_key = f"alt_props_{event_id}"
    cached = cache_get(cache_key, config.CACHE_TTL["props"])
    if cached is not None:
        return cached

    markets_str = ",".join(config.ALTERNATE_MARKET_MAP)
    data = _get(
        f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
        # Alternate lines are only offered by US bookmakers (FanDuel, DraftKings, etc.)
        # EU region (used for standard props / Paddy Power) has none.
        {"regions": config.ALTERNATE_ODDS_REGIONS, "markets": markets_str},
    )
    if not data:
        return []

    bookmakers = data.get("bookmakers", [])
    results = _extract_alternate_props(bookmakers, config.ALTERNATE_MARKET_MAP)
    cache_set(cache_key, results)
    return results


# ---------------------------------------------------------------------------
# Build PlayerProp objects from raw prop dicts
# ---------------------------------------------------------------------------

def build_player_props(
    raw_props: list[dict],
    game: NBAGame,
    player_id_map: dict[str, int],
) -> list[PlayerProp]:
    """
    Convert raw prop dicts to PlayerProp objects.
    player_id_map: {player_name: nba_player_id}
    Skips props where player_id is unknown.
    """
    props: list[PlayerProp] = []
    for p in raw_props:
        name = p["player_name"]
        pid = player_id_map.get(name)
        if not pid:
            continue
        if p["over_odds"] <= 0.0:
            continue

        props.append(
            PlayerProp(
                player_name=name,
                nba_player_id=pid,
                market=p["market"],
                line=p["line"],
                over_odds_decimal=p["over_odds"],
                under_odds_decimal=p["under_odds"],
                bookmaker=p["bookmaker"],
                game=game,
                is_paddy_power=p["is_paddy_power"],
                is_alternate=p.get("is_alternate", False),
            )
        )
    return props
