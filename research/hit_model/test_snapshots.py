import pickle

import snapshots


def test_snapshots_fetched_once_per_date_and_cached(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(snapshots, "fetch_snapshot", lambda season, through: calls.append(through) or {"t": through})
    monkeypatch.setattr(snapshots.time, "sleep", lambda s: None)
    cache = tmp_path / "snaps.pkl"
    out = snapshots.snapshots_for_dates("2025-26", ["2026-03-02", "2026-03-01", "2026-03-02"], str(cache))
    assert calls == ["2026-02-28", "2026-03-01"]            # as of the day before each game
    assert out["2026-03-02"] == {"t": "2026-03-01"}
    snapshots.snapshots_for_dates("2025-26", ["2026-03-01"], str(cache))
    assert len(calls) == 2 and pickle.load(open(cache, "rb")).keys() == {"2026-03-01", "2026-03-02"}


def test_retries_on_failure(tmp_path, monkeypatch):
    attempts = []
    def flaky(season, through):
        attempts.append(1)
        if len(attempts) < 2:
            raise TimeoutError
        return {"ok": True}
    monkeypatch.setattr(snapshots, "fetch_snapshot", flaky)
    monkeypatch.setattr(snapshots.time, "sleep", lambda s: None)
    assert snapshots.snapshots_for_dates("2025-26", ["2026-03-01"], str(tmp_path / "s.pkl"))["2026-03-01"] == {"ok": True}
