import json
import os
import time
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import cache


@pytest.fixture
def counter(monkeypatch, fresh_cache):
    monkeypatch.setattr(cache, "_COUNTER_FILE", str(fresh_cache / "api_credits.json"))
    return fresh_cache


def test_get_set_ttl_and_invalidate(fresh_cache):
    cache.set("a/b:c?d&e", {"x": 1})
    assert cache.get("a/b:c?d&e", 60) == {"x": 1}
    assert cache.get("a/b:c?d&e", -1) is None              # expired
    assert cache.get("missing", 60) is None
    cache.invalidate("a/b:c?d&e")
    assert cache.get("a/b:c?d&e", 60) is None
    cache.invalidate("never-existed")


def test_corrupt_file_is_a_miss(fresh_cache):
    (fresh_cache / "bad.json").write_text("{not json")
    assert cache.get("bad", 60) is None


def test_encoder_handles_numpy_and_dates(fresh_cache):
    cache.set("k", {"n": np.int64(3), "f": np.float64(1.5), "d": pd.Timestamp("2026-01-02"), "day": date(2026, 1, 3)})
    assert cache.get("k", 60) == {"n": 3, "f": 1.5, "d": "2026-01-02T00:00:00", "day": "2026-01-03"}
    with pytest.raises(TypeError):
        cache.set("bad", {"x": object()})


def test_scored_props_roundtrip(fresh_cache):
    cache.save_scored_props([{"p": 1}], "2026-03-01")
    assert cache.load_scored_props_raw("2026-03-01") == [{"p": 1}]
    cache.save_scored_props([{"p": 2}])
    assert cache.load_scored_props_raw() == [{"p": 2}]


def test_credit_counter(counter):
    assert cache.get_credits_used() == 0
    cache.record_api_request(3)
    assert cache.get_credits_used() == 3
    cache.sync_credits_from_header(used=40, remaining=460)
    assert cache.get_credits_used() == 40 and cache.get_credits_remaining() == 460
    assert "40/500" in cache.credits_summary()
    assert cache.warn_if_low(threshold=50) is None
    cache.sync_credits_from_header(used=480, remaining=20)
    assert "20" in cache.warn_if_low(threshold=50)


def test_counter_resets_on_new_month_or_key(counter, monkeypatch):
    cache.sync_credits_from_header(used=100)
    monkeypatch.setattr(cache, "_current_month", lambda: "2099-01")
    assert cache.get_credits_used() == 0
