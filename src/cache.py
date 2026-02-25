"""
File-based cache with TTLs and Odds API request counter.

All API modules call cache.get / cache.set.
The request counter lives in .cache/api_credits.json and persists across runs.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, date
from typing import Any

import config


class _Encoder(json.JSONEncoder):
    """Handles types that pandas/nba_api produce that stock json can't handle."""
    def default(self, obj: Any) -> Any:
        # pandas Timestamp, datetime, date → ISO string
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        # numpy int/float scalars
        if hasattr(obj, "item"):
            return obj.item()
        return super().default(obj)

_COUNTER_FILE = os.path.join(config.CACHE_DIR, "api_credits.json")
_MONTHLY_LIMIT_DEFAULT = 500   # fallback if we haven't seen a response header yet


def _ensure_dir() -> None:
    os.makedirs(config.CACHE_DIR, exist_ok=True)


def _cache_path(key: str) -> str:
    safe = key.replace("/", "_").replace(":", "_").replace("?", "_").replace("&", "_")
    return os.path.join(config.CACHE_DIR, f"{safe}.json")


# ---------------------------------------------------------------------------
# Cache get / set
# ---------------------------------------------------------------------------

def get(key: str, ttl_seconds: int) -> Any | None:
    """Return cached value if it exists and is not stale, else None."""
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            entry = json.load(f)
        if time.time() - entry["ts"] > ttl_seconds:
            return None
        return entry["data"]
    except (json.JSONDecodeError, KeyError):
        return None


def set(key: str, data: Any) -> None:
    """Persist data to cache with current timestamp."""
    _ensure_dir()
    path = _cache_path(key)
    with open(path, "w") as f:
        json.dump({"ts": time.time(), "data": data}, f, cls=_Encoder)


def invalidate(key: str) -> None:
    path = _cache_path(key)
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# Scored-props persistence (ValuedProp serialised as plain dicts)
# ---------------------------------------------------------------------------

def save_scored_props(prop_dicts: list[dict], date_str: str | None = None) -> None:
    """
    Persist a list of ValuedProp dicts (output of dataclasses.asdict) to cache.
    Keyed by date so each day's grade run is stored independently.
    TTL is 36 hours — long enough to survive overnight but fresh daily.
    """
    if date_str is None:
        date_str = date.today().isoformat()
    set(f"scored_props_{date_str}", prop_dicts)


def load_scored_props_raw(
    date_str: str | None = None,
    max_age_seconds: int = 129_600,   # 36 hours
) -> list[dict] | None:
    """
    Return the cached list of ValuedProp dicts, or None if absent / stale.
    Callers are responsible for reconstructing ValuedProp objects from the dicts.
    """
    if date_str is None:
        date_str = date.today().isoformat()
    return get(f"scored_props_{date_str}", max_age_seconds)


# ---------------------------------------------------------------------------
# Odds API credit counter
# ---------------------------------------------------------------------------

def _load_counter() -> dict:
    if not os.path.exists(_COUNTER_FILE):
        return {"month": _current_month(), "used": 0}
    with open(_COUNTER_FILE) as f:
        return json.load(f)


def _save_counter(counter: dict) -> None:
    _ensure_dir()
    with open(_COUNTER_FILE, "w") as f:
        json.dump(counter, f)


def _current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def record_api_request(n: int = 1) -> None:
    """
    Fallback: increment the local counter by n.
    Used only when the API response headers are unavailable.
    Prefer sync_credits_from_header() for accuracy.
    """
    counter = _load_counter()
    if counter["month"] != _current_month():
        counter = {"month": _current_month(), "used": 0}
    counter["used"] += n
    _save_counter(counter)


def sync_credits_from_header(used: int, remaining: int | None = None) -> None:
    """
    Overwrite the local counter with ground-truth values from the
    x-requests-used (and optionally x-requests-remaining) response headers.

    This is called after every successful Odds API HTTP response so we always
    reflect reality rather than our own (inaccurate) manual counting.
    If remaining is provided we also store the inferred monthly limit so the
    credits_summary() display is accurate for any plan tier.
    """
    _ensure_dir()
    counter = {"month": _current_month(), "used": used}
    if remaining is not None:
        counter["limit"] = used + remaining   # e.g. 47 used + 453 remaining = 500 limit
    _save_counter(counter)


def _get_monthly_limit() -> int:
    """Return the stored limit (learned from headers) or the default fallback."""
    counter = _load_counter()
    return counter.get("limit", _MONTHLY_LIMIT_DEFAULT)


def get_credits_used() -> int:
    counter = _load_counter()
    if counter["month"] != _current_month():
        return 0
    return counter["used"]


def get_credits_remaining() -> int:
    return max(0, _get_monthly_limit() - get_credits_used())


def credits_summary() -> str:
    used = get_credits_used()
    limit = _get_monthly_limit()
    remaining = max(0, limit - used)
    pct = (used / limit) * 100 if limit else 0
    return f"Odds API: {used}/{limit} used ({pct:.0f}%) | {remaining} remaining this month"


def warn_if_low(threshold: int = 50) -> str | None:
    """Return a warning string if credits are running low, else None."""
    remaining = get_credits_remaining()
    if remaining <= threshold:
        return (
            f"[WARNING] Only {remaining} Odds API credits remaining this month. "
            "Results may use cached data."
        )
    return None
