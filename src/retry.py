"""Small retry-with-backoff helper for transient failures in external API calls.

Used by odds_api and nba_stats so a single dropped connection or rate-limit
blip doesn't silently turn into "no games" / "no props" for the whole refresh.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[T], bool] | None = None,
    on_retry: Callable[[int, BaseException | None], None] | None = None,
) -> T | None:
    """
    Call fn() up to max_attempts times with exponential backoff (1s, 3s, 9s, ...).

    - retry_on: exception types that trigger a retry (others propagate immediately).
    - should_retry: optional predicate on a *successful* return value — return True
      to retry anyway (e.g. got a 429/5xx response object back instead of a raised
      exception). If it returns False, the result is returned immediately.
    - on_retry(attempt, exc): called before each sleep, exc is None if the retry
      was triggered by should_retry rather than an exception.

    Returns the last successful (or last obtained) value, or None if every
    attempt raised a retry_on exception.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
        except retry_on as exc:
            last_exc = exc
            if attempt == max_attempts:
                return None
            if on_retry:
                on_retry(attempt, exc)
            time.sleep(base_delay * (3 ** (attempt - 1)))
            continue

        if should_retry is not None and should_retry(result) and attempt < max_attempts:
            if on_retry:
                on_retry(attempt, None)
            time.sleep(base_delay * (3 ** (attempt - 1)))
            continue

        return result

    return None
