"""
The Odds API wrapper.
Fetches game lines (spreads) and player props for tonight's NBA games.
Prefers Paddy Power; falls back to best available if PP doesn't offer a market.
API credit usage is tracked via src/cache.py.

Supports a pool of API keys (ODDS_API_KEYS env var, comma-separated).
On each request the key with the most remaining credits is used automatically.
Exhausted keys (0 remaining or 403) are skipped until the pool is replenished.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import requests
from typing import Any

import config
import sys
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
# API Key Pool — automatic rotation across multiple keys
# ---------------------------------------------------------------------------

_pool_lock = threading.Lock()

# Per-key credit state: {key_hash: {"used": int, "remaining": int, "exhausted": bool}}
_key_credits: dict[str, dict] = {}

# Persistent cache file for key credits (survives restarts)
_KEY_POOL_FILE = os.path.join(
    os.getenv("CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cache")),
    "key_pool.json",
)


def _khash(key: str) -> str:
    """Short hash for logging (never log the full key)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _load_pool_state() -> None:
    """Load persisted per-key credit state from disk."""
    global _key_credits
    if os.path.exists(_KEY_POOL_FILE):
        try:
            with open(_KEY_POOL_FILE) as f:
                _key_credits = json.load(f)
        except (json.JSONDecodeError, OSError):
            _key_credits = {}
    # Ensure every configured key has an entry
    for key in config.ODDS_API_KEYS:
        kh = _khash(key)
        if kh not in _key_credits:
            _key_credits[kh] = {"used": 0, "remaining": 500, "exhausted": False}


def _save_pool_state() -> None:
    """Persist per-key credit state to disk."""
    try:
        os.makedirs(os.path.dirname(_KEY_POOL_FILE), exist_ok=True)
        with open(_KEY_POOL_FILE, "w") as f:
            json.dump(_key_credits, f)
    except OSError:
        pass


def _pick_best_key() -> str | None:
    """Return the API key with the most remaining credits, skipping exhausted keys."""
    best_key: str | None = None
    best_remaining = -1
    for key in config.ODDS_API_KEYS:
        kh = _khash(key)
        state = _key_credits.get(kh, {})
        if state.get("exhausted", False):
            continue
        rem = state.get("remaining", 500)
        if rem > best_remaining:
            best_remaining = rem
            best_key = key
    return best_key


def _update_key_credits(key: str, used: int, remaining: int | None) -> None:
    """Update credit state for a specific key after an API response."""
    kh = _khash(key)
    entry = _key_credits.setdefault(kh, {"used": 0, "remaining": 500, "exhausted": False})
    entry["used"] = used
    if remaining is not None:
        entry["remaining"] = remaining
        if remaining <= 0:
            entry["exhausted"] = True
            print(f"[key-pool] Key ...{kh} exhausted (0 remaining) — rotating to next key")
    _save_pool_state()


def _mark_exhausted(key: str) -> None:
    """Mark a key as exhausted (e.g. after a 403)."""
    kh = _khash(key)
    entry = _key_credits.setdefault(kh, {"used": 0, "remaining": 0, "exhausted": False})
    entry["exhausted"] = True
    entry["remaining"] = 0
    print(f"[key-pool] Key ...{kh} marked exhausted (403)")
    _save_pool_state()


def get_pool_credits() -> dict:
    """Return aggregate credit info across all keys in the pool."""
    with _pool_lock:
        total_remaining = 0
        total_used = 0
        total_limit = 0
        keys_info = []
        for key in config.ODDS_API_KEYS:
            kh = _khash(key)
            state = _key_credits.get(kh, {"used": 0, "remaining": 500, "exhausted": False})
            used = state.get("used", 0)
            rem = state.get("remaining", 500)
            total_used += used
            total_remaining += rem
            total_limit += used + rem
            keys_info.append({
                "key_hash": kh,
                "used": used,
                "remaining": rem,
                "exhausted": state.get("exhausted", False),
            })
        return {
            "used": total_used,
            "remaining": total_remaining,
            "total": total_limit,
            "keys": keys_info,
            "active_keys": sum(1 for k in keys_info if not k["exhausted"]),
            "total_keys": len(keys_info),
        }


# Initialise pool state on import
_load_pool_state()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict) -> dict | list | None:
    """Make a GET request to The Odds API using the best available key."""
    with _pool_lock:
        api_key = _pick_best_key()
    if not api_key:
        print("[odds-api] ❌ No API keys available (all exhausted or none configured)")
        return None

    params["apiKey"] = api_key
    params.setdefault("oddsFormat", "decimal")
    url = f"{config.ODDS_API_BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        # Sync credit counter from response headers
        raw_used = resp.headers.get("x-requests-used")
        raw_remaining = resp.headers.get("x-requests-remaining")
        if raw_used is not None:
            try:
                used_val = int(raw_used)
                rem_val = int(raw_remaining) if raw_remaining is not None else None
                with _pool_lock:
                    _update_key_credits(api_key, used_val, rem_val)
                # Also sync the global counter (for backwards compat with /api/credits)
                sync_credits_from_header(used=used_val, remaining=rem_val)
            except ValueError:
                record_api_request(1)
        else:
            record_api_request(1)

        if resp.status_code == 401:
            print(f"[odds-api] ❌ Key ...{_khash(api_key)} rejected (401)")
            with _pool_lock:
                _mark_exhausted(api_key)
            return None
        if resp.status_code == 403:
            print(f"[odds-api] ❌ Key ...{_khash(api_key)} out of credits (403)")
            with _pool_lock:
                _mark_exhausted(api_key)
            # Retry once with the next best key
            with _pool_lock:
                next_key = _pick_best_key()
            if next_key and next_key != api_key:
                print(f"[odds-api] ↻ Retrying with key ...{_khash(next_key)}")
                params["apiKey"] = next_key
                resp2 = requests.get(url, params=params, timeout=15)
                raw_used2 = resp2.headers.get("x-requests-used")
                raw_remaining2 = resp2.headers.get("x-requests-remaining")
                if raw_used2 is not None:
                    try:
                        with _pool_lock:
                            _update_key_credits(next_key, int(raw_used2),
                                int(raw_remaining2) if raw_remaining2 else None)
                    except ValueError:
                        pass
                if resp2.status_code in (401, 403):
                    with _pool_lock:
                        _mark_exhausted(next_key)
                    return None
                if resp2.status_code == 429:
                    return None
                resp2.raise_for_status()
                return resp2.json()
            return None
        if resp.status_code == 429:
            print(f"[odds-api] ❌ Rate limited (429) — too many requests")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        print(f"[odds-api] ⚠️ Request failed: {exc}")
        return None


def _decimal_odds(price: float | None) -> float:
    """Ensure odds are in decimal format (we request oddsFormat=decimal)."""
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
    cached = cache_get(cache_key, config.CACHE_TTL["events"])
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


def _build_abbr_lookup() -> dict[str, str]:
    """
    Build a lookup that maps various team name forms to 3-letter abbreviations.
    Handles: full name, city, nickname, common variations.
    Keys are lowercase. Values are uppercase abbreviations.
    """
    from nba_api.stats.static import teams as nba_teams_static

    lookup: dict[str, str] = {}
    for t in nba_teams_static.get_teams():
        abbr = t["abbreviation"].upper()
        # Direct abbreviation
        lookup[abbr.lower()] = abbr
        # Full name: "New York Knicks"
        lookup[t["full_name"].lower()] = abbr
        # Nickname: "Knicks"
        lookup[t["nickname"].lower()] = abbr
        # City: "New York"
        lookup[t["city"].lower()] = abbr

    # Common variations the Odds API might use
    lookup["la clippers"] = "LAC"
    lookup["la lakers"] = "LAL"
    lookup["los angeles clippers"] = "LAC"
    lookup["los angeles lakers"] = "LAL"
    return lookup


# Module-level cache — built once on first use
_ABBR_LOOKUP: dict[str, str] | None = None


def _normalise_team(name: str) -> str:
    """
    Convert any team name format to a 3-letter abbreviation.
    Handles: "New York Knicks", "Knicks", "NYK", "New York" → "NYK"
    Returns the input lowercased if no match found.
    """
    global _ABBR_LOOKUP
    if _ABBR_LOOKUP is None:
        _ABBR_LOOKUP = _build_abbr_lookup()

    key = name.strip().lower()
    if key in _ABBR_LOOKUP:
        return _ABBR_LOOKUP[key]

    # Partial match — check if any known name is contained in the input
    for known, abbr in _ABBR_LOOKUP.items():
        if len(known) > 3 and known in key:
            return abbr

    return key  # fallback: return as-is


def match_game_to_event(game: NBAGame, events: list[dict]) -> str | None:
    """
    Match an NBAGame (with 3-letter team abbreviations) to an Odds API event
    (with full team names like "New York Knicks").

    Strategy:
      1. Normalise both sides to 3-letter abbreviations, then exact match.
      2. Fuzzy fallback using normalised names (lower threshold).

    Returns the event_id string or None.
    """
    if not events:
        return None

    home_abbr = _normalise_team(game.home_team)
    away_abbr = _normalise_team(game.away_team)

    # --- Pass 1: Exact abbreviation match ---
    for event in events:
        ev_home = _normalise_team(event.get("home_team", ""))
        ev_away = _normalise_team(event.get("away_team", ""))
        if ev_home == home_abbr and ev_away == away_abbr:
            return event["id"]

    # --- Pass 2: Relaxed — match ignoring home/away swap (rare but possible) ---
    for event in events:
        ev_home = _normalise_team(event.get("home_team", ""))
        ev_away = _normalise_team(event.get("away_team", ""))
        if {ev_home, ev_away} == {home_abbr, away_abbr}:
            return event["id"]

    # --- Pass 3: Fuzzy fallback (substring + thefuzz) ---
    from thefuzz import process

    home_lower = game.home_team.lower()
    away_lower = game.away_team.lower()

    # Direct substring check (handles cases like abbreviation in full name)
    for event in events:
        home_team = event.get("home_team", "").lower()
        away_team = event.get("away_team", "").lower()
        if (home_lower in home_team or home_team in home_lower) and (
            away_lower in away_team or away_team in away_lower
        ):
            return event["id"]

    # Fuzzy matching as last resort
    all_matchups = [
        f"{e.get('away_team', '')} @ {e.get('home_team', '')}"
        for e in events
    ]
    target = f"{game.away_team} @ {game.home_team}"
    if all_matchups:
        match, score = process.extractOne(target, all_matchups)
        if score >= 60:  # lowered from 70 — abbreviations are short strings
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
    cached = cache_get(cache_key, config.CACHE_TTL["spreads"])
    if cached is not None:
        return float(cached)

    # Single call — any bookmaker in the EU region (1 credit)
    data = _get(
        f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
        {
            "regions": "eu",
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
    force_fresh: bool = False,
) -> list[dict]:
    """
    Fetch all player prop outcomes for an event.
    Returns raw outcome dicts with player_name, market, line, over_odds, under_odds,
    bookmaker, is_paddy_power.

    Two targeted calls to minimise credit usage:
      1. EU region for core markets (Bet365/PP) — 5 markets × 1 credit each
      2. US region for combo markets EU doesn't carry — 3 markets × 1 credit each
    Total: 8 credits per game (same as single-region with 8 markets).

    If force_fresh=True, cached props are ignored (used by smart refresh).
    """
    if markets is None:
        markets = list(config.MARKET_MAP.keys())

    cache_key = f"props_{event_id}_{'_'.join(sorted(markets))}"
    if not force_fresh:
        cached = cache_get(cache_key, config.CACHE_TTL["props"])
        if cached is not None:
            return cached

    results: list[dict] = []

    # Split markets by region to avoid 2x credit charge from eu,us
    eu_markets = [m for m in markets if m in config.EU_MARKETS]
    us_markets = [m for m in markets if m in config.US_ONLY_MARKETS]

    # Call 1: EU region — core markets from Bet365/Paddy Power
    if eu_markets:
        data = _get(
            f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
            {
                "regions": config.ODDS_REGIONS,
                "markets": ",".join(eu_markets),
            },
        )
        if data:
            results.extend(_extract_props(data.get("bookmakers", []), eu_markets))

    # Call 2: US region — combo markets (PR, PA, RA) not offered by EU books
    # Restrict to clean single-line bookmakers (exclude Bovada multi-line)
    if us_markets:
        data = _get(
            f"/sports/{config.ODDS_SPORT}/events/{event_id}/odds",
            {
                "regions": config.ODDS_REGIONS_US,
                "markets": ",".join(us_markets),
                "bookmakers": config.US_COMBO_BOOKMAKERS,
            },
        )
        if data:
            results.extend(_extract_props(data.get("bookmakers", []), us_markets))

    cache_set(cache_key, results)
    return results


def _extract_props(bookmakers: list[dict], markets: list[str]) -> list[dict]:
    """
    Extract player props from bookmakers list.
    Returns one entry per (player, market) — picks the best available odds.
    When multiple bookmakers offer the same prop, keeps the one with the
    highest over odds (best value for the bettor).
    """
    # Index: (player_name, market) → best odds seen so far
    index: dict[tuple[str, str], dict] = {}

    for bm in bookmakers:
        bm_key = bm["key"]
        for market in bm.get("markets", []):
            mkt = market["key"]
            if mkt not in markets:
                continue

            # Group outcomes by (player, line) to avoid cross-line mismatches
            # when a bookmaker offers multiple lines (e.g. Bovada: O4.5, O5.5, O6.5)
            line_outcomes: dict[tuple[str, float], dict] = {}
            for outcome in market.get("outcomes", []):
                player = outcome.get("description", "")
                if not player:
                    continue
                side = outcome.get("name", "")
                point = outcome.get("point")
                if point is None:
                    continue
                price = _decimal_odds(outcome.get("price"))

                lk = (player, float(point))
                if lk not in line_outcomes:
                    line_outcomes[lk] = {"over": None, "under": None, "line": point}

                if side == "Over":
                    line_outcomes[lk]["over"] = price
                elif side == "Under":
                    line_outcomes[lk]["under"] = price

            # Pick ONE line per player: prefer the line closest to even odds
            # (middle line = primary, extremes = alternates)
            player_outcomes: dict[str, dict] = {}
            for (player, _pt), od in line_outcomes.items():
                if od["over"] is None or od["under"] is None:
                    continue
                balance = abs(od["over"] - od["under"])
                if player not in player_outcomes or balance < player_outcomes[player]["_balance"]:
                    player_outcomes[player] = {**od, "_balance": balance}

            for od in player_outcomes.values():
                od.pop("_balance", None)

            for player, odds_data in player_outcomes.items():
                key = (player, mkt)
                over = odds_data["over"] or 0.0
                under = odds_data["under"] or 0.0

                # Keep whichever bookmaker offers the best over odds
                if key not in index or over > index[key]["over_odds"]:
                    index[key] = {
                        "player_name":    player,
                        "market":         mkt,
                        "line":           float(odds_data["line"]),
                        "over_odds":      over,
                        "under_odds":     under,
                        "bookmaker":      bm_key,
                        "is_paddy_power": False,
                    }

    return [d for d in index.values() if d["line"] is not None]


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


# ---------------------------------------------------------------------------
# Smart refresh helpers
# ---------------------------------------------------------------------------

def invalidate_props_cache() -> int:
    """
    Remove all cached props files so the next fetch hits the API fresh.
    Returns the number of cache files removed.
    """
    import glob
    pattern = os.path.join(config.CACHE_DIR, "props_*.json")
    files = glob.glob(pattern)
    for f in files:
        os.remove(f)
    return len(files)
