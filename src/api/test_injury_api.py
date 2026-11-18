import pytest
import requests

from src.api import injury_api as ia
from src.models import InjuryReport

ESPN = {"injuries": [
    {"team": {"abbreviation": "GS"}, "injuries": [
        {"athlete": {"displayName": "Stephen Curry"}, "status": "Day-To-Day"},
        {"athlete": {"displayName": "Draymond Green", "team": {"abbreviation": "GS"}}, "status": "Out"},
    ]},
    {"team": {}, "injuries": [
        {"athlete": {"displayName": "Trey Alexander", "team": {"abbreviation": "UTAH"}}, "status": "Injured Reserve"},
        {"athlete": {"displayName": ""}, "status": "Out"},
    ]},
]}


class Resp:
    def __init__(self, data, ok=True):
        self._data, self._ok = data, ok

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("500")

    def json(self):
        return self._data


def test_parses_and_normalises_espn(monkeypatch, fresh_cache):
    monkeypatch.setattr(ia.requests, "get", lambda *a, **k: Resp(ESPN))
    reports = ia.get_injury_report()
    by_name = {r.player_name: r for r in reports}
    assert by_name["Stephen Curry"].status == "questionable" and by_name["Stephen Curry"].team == "GSW"
    assert by_name["Draymond Green"].status == "out"
    assert by_name["Trey Alexander"].team == "UTA" and by_name["Trey Alexander"].status == "out"
    assert len(reports) == 3
    # cached second time — no network
    monkeypatch.setattr(ia.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("refetched")))
    assert len(ia.get_injury_report()) == 3


def test_failure_returns_empty(monkeypatch, fresh_cache):
    monkeypatch.setattr(ia.requests, "get", lambda *a, **k: Resp({}, ok=False))
    assert ia.get_injury_report() == []


def test_status_lookup_is_exact_not_fuzzy():
    reports = [InjuryReport("Trey Alexander", "UTA", "out"), InjuryReport("Herbert Jones", "NOP", "doubtful")]
    assert ia.get_player_status("Shai Gilgeous-Alexander", reports) is None
    assert ia.get_player_status("Herb Jones", reports) == "doubtful"
    assert ia.get_player_status("Anyone", []) is None


def test_helpers():
    reports = [InjuryReport("A", "BOS", "out"), InjuryReport("B", "nyk", "probable")]
    assert [r.player_name for r in ia.get_team_injuries("NYK", reports)] == ["B"]
    assert ia.is_player_unavailable("doubtful") and not ia.is_player_unavailable("questionable")
    assert ia.injury_severity_score("out") == 0.0 and ia.injury_severity_score(None) == 1.0
    assert ia.injury_severity_score("weird") == 1.0
