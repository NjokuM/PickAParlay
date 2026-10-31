"""
League-wide stat tables "as of" a date — what was known the morning of a game.

Used by research/hit_model to rebuild features for past props, and by live
grading (src/api/league_tables.get_snapshot) for today. Same endpoints,
same columns, so the model sees identical inputs in training and production.
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.api.league_tables import TABLES, fetch_snapshot  # noqa: E402,F401  (shared with live grading)


def snapshots_for_dates(season: str, game_dates: list[str], cache_file: str) -> dict[str, dict]:
    """As-of snapshot (games through the day before) for each game date, cached on disk."""
    cache = pickle.load(open(cache_file, "rb")) if os.path.exists(cache_file) else {}
    for d in sorted(set(game_dates)):
        if d in cache:
            continue
        through = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        for attempt in range(3):
            try:
                cache[d] = fetch_snapshot(season, through)
                break
            except Exception as exc:
                print(f"  {d}: attempt {attempt + 1} failed: {exc}")
                time.sleep(10 * (attempt + 1))
        pickle.dump(cache, open(cache_file, "wb"))
        print(f"  snapshot {d} ({len(cache)}/{len(set(game_dates))})", flush=True)
    return cache


if __name__ == "__main__":
    # python research/hit_model/snapshots.py <season> <cache_file> <date> [<date> ...]
    snapshots_for_dates(sys.argv[1], [d for a in sys.argv[3:] for d in a.split()], sys.argv[2])
