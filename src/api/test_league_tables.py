import pandas as pd
import pytest

from src.api import league_tables as lt


class FakeEndpoint:
    calls = []

    def __init__(self, **kw):
        FakeEndpoint.calls.append(kw)

    def get_data_frames(self):
        return [pd.DataFrame({"PLAYER_ID": [1, 2], "TEAM_ID": [1610612738, 1610612752], "MIN": ["30", "0"], "X": [1, 2]})]


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeEndpoint.calls = []
    monkeypatch.setattr(lt, "_memo", {})
    monkeypatch.setattr(lt, "TABLES", {k: (FakeEndpoint, p, i) for k, (_, p, i) in lt.TABLES.items()})
    monkeypatch.setattr(lt, "LeagueGameLog", FakeEndpoint)


def test_fetch_snapshot_indexes_and_dates():
    snap = lt.fetch_snapshot("2025-26", through="2026-03-01")
    assert set(snap) == set(lt.TABLES)
    assert list(snap["tadv"].index) == ["BOS", "NYK"]           # team abbreviations added from TEAM_ID
    assert list(snap["cs"].index) == [1, 2]
    assert FakeEndpoint.calls[0]["date_to_nullable"] == "03/01/2026"


def test_snapshot_memoised():
    lt.get_snapshot("2026-27"); lt.get_snapshot("2026-27")
    assert len(FakeEndpoint.calls) == len(lt.TABLES)


def test_league_log_drops_dnps():
    df = lt.get_league_player_log("2026-27")
    assert df.MIN.tolist() == [30.0]


def test_failures_back_off(monkeypatch):
    calls = []
    def boom():
        calls.append(1); raise TimeoutError
    assert lt._memoised("k", boom) is None and lt._memoised("k", boom) is None
    assert len(calls) == 1
