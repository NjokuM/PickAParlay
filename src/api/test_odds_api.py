import json
import sqlite3

import pytest
import requests

import config
from testkit import make_prop
from src.api import odds_api as oa
from src.models import NBAGame


class Resp:
    def __init__(self, status=200, data=None, used="10", remaining="490"):
        self.status_code, self._data = status, data
        self.headers = {} if used is None else {"x-requests-used": used, "x-requests-remaining": remaining}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def pool(monkeypatch, fresh_cache):
    monkeypatch.setattr(config, "ODDS_API_KEYS", ["key-a", "key-b"])
    monkeypatch.setattr(oa, "_KEY_POOL_FILE", str(fresh_cache / "key_pool.json"))
    monkeypatch.setattr(oa, "_key_credits", {})
    monkeypatch.setattr(oa, "sync_credits_from_header", lambda **k: None)
    monkeypatch.setattr(oa, "record_api_request", lambda n=1: None)
    oa._load_pool_state()


def respond(monkeypatch, *responses):
    seq = list(responses)
    sent = []
    def fake_get(url, params=None, timeout=None):
        sent.append(dict(params))
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(oa.requests, "get", fake_get)
    return sent


def test_pool_picks_key_with_most_credits(pool):
    oa._update_key_credits("key-a", 100, 400)
    oa._update_key_credits("key-b", 10, 490)
    assert oa._pick_best_key() == "key-b"
    oa._mark_exhausted("key-b")
    assert oa._pick_best_key() == "key-a"
    oa._update_key_credits("key-a", 500, 0)
    assert oa._pick_best_key() is None
    credits = oa.get_pool_credits()
    assert credits["active_keys"] == 0 and credits["total_keys"] == 2


def test_pool_state_persists(pool):
    oa._update_key_credits("key-a", 7, 493)
    oa._key_credits.clear()
    oa._load_pool_state()
    assert oa._key_credits[oa._khash("key-a")]["used"] == 7


def test_get_success_and_failures(pool, monkeypatch):
    respond(monkeypatch, Resp(data={"ok": 1}))
    assert oa._get("/x", {}) == {"ok": 1}
    respond(monkeypatch, Resp(status=401))
    assert oa._get("/x", {}) is None
    respond(monkeypatch, Resp(status=429))
    assert oa._get("/x", {}) is None
    respond(monkeypatch, requests.ConnectionError("down"))
    assert oa._get("/x", {}) is None
    respond(monkeypatch, Resp(data={"ok": 2}, used=None))
    assert oa._get("/x", {}) == {"ok": 2}


def test_403_rotates_to_next_key(pool, monkeypatch):
    sent = respond(monkeypatch, Resp(status=403), Resp(data={"ok": 3}))
    assert oa._get("/x", {}) == {"ok": 3}
    assert sent[0]["apiKey"] != sent[1]["apiKey"]
    respond(monkeypatch, Resp(status=403), Resp(status=403))
    assert oa._get("/x", {}) is None
    assert oa._pick_best_key() is None


BOOKS = [
    {"key": "fanduel", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "Jane Doe", "point": 20.5, "price": 1.9},
        {"name": "Under", "description": "Jane Doe", "point": 20.5, "price": 1.9},
        {"name": "Over", "description": "Jane Doe", "point": 25.5, "price": 3.0},   # alt-ish line: unbalanced
        {"name": "Under", "description": "Jane Doe", "point": 25.5, "price": 1.3},
    ]}]},
    {"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "Jane Doe", "point": 21.5, "price": 2.05},
        {"name": "Under", "description": "Jane Doe", "point": 21.5, "price": 1.78},
    ]}]},
]


def test_extract_props_keeps_balanced_line_and_best_over():
    props = oa._extract_props(BOOKS, ["player_points"])
    assert len(props) == 1
    assert props[0]["bookmaker"] == "draftkings" and props[0]["line"] == 21.5


def test_extract_alternate_props_and_odds_helpers(monkeypatch):
    monkeypatch.setattr(config, "PREFERRED_BOOKMAKER", "fanduel")
    alts = oa._extract_alternate_props(BOOKS, ["player_points"])
    assert {a["line"] for a in alts} == {20.5, 21.5, 25.5}
    assert oa._best_odds_for_market(BOOKS, "player_points", "jane doe", "Over") == (3.0, "fanduel")
    assert oa._paddy_odds_for_market(BOOKS, "player_points", "Jane Doe", "Over") == 1.9
    assert oa._paddy_odds_for_market([], "player_points", "Jane Doe", "Over") == 0.0
    assert oa._decimal_odds(None) == 0.0 and oa._decimal_odds(2.123456) == 2.123


def test_snapshot_captures_every_book(fresh_db):
    oa._snapshot_odds("evt", {"commence_time": "2026-04-01T23:30:00Z", "bookmakers": BOOKS}, ["player_points"])
    with sqlite3.connect(config.DATABASE_PATH) as c:
        rows = c.execute("SELECT bookmaker, line, game_date FROM odds_snapshots ORDER BY line").fetchall()
    assert rows == [("fanduel", 20.5, "2026-04-01"), ("draftkings", 21.5, "2026-04-01"), ("fanduel", 25.5, "2026-04-01")]
    oa._snapshot_odds("evt", None, ["player_points"])            # swallowed, never raises


def test_props_for_event_calls_eu_and_us_and_caches(pool, monkeypatch, fresh_db):
    sent = respond(monkeypatch, Resp(data={"bookmakers": BOOKS}), Resp(data={"bookmakers": []}))
    props = oa.get_player_props_for_event("evt", markets=["player_points", "player_points_rebounds"], force_fresh=True)
    assert len(props) == 1 and len(sent) == 2
    assert sent[1]["bookmakers"] == config.US_COMBO_BOOKMAKERS
    assert oa.get_player_props_for_event("evt", markets=["player_points", "player_points_rebounds"]) == props


def test_events_spread_and_alternates(pool, monkeypatch):
    respond(monkeypatch, Resp(data=[{"id": "e1"}]))
    assert oa.get_events() == [{"id": "e1"}] and oa.get_events() == [{"id": "e1"}]
    spread_books = [{"key": "fanduel", "markets": [{"key": "spreads", "outcomes": [{"name": "BOS", "point": -4.5}]}]}]
    respond(monkeypatch, Resp(data={"bookmakers": spread_books}))
    assert oa.get_game_spread("e1") == -4.5 and oa.get_game_spread("e1") == -4.5
    assert oa._extract_spread([]) is None
    respond(monkeypatch, Resp(data={"bookmakers": BOOKS}))
    monkeypatch.setattr(config, "ALTERNATE_MARKET_MAP", ["player_points"])
    assert oa.get_alternate_props_for_event("e1")
    respond(monkeypatch, Resp(status=401))
    assert oa.get_alternate_props_for_event("e2") == []


def test_team_matching():
    game = NBAGame("1", "NYK", "BOS", 1, 2, "2026-04-01", "", "")
    events = [{"id": "x", "home_team": "Miami Heat", "away_team": "Chicago Bulls"},
              {"id": "y", "home_team": "New York Knicks", "away_team": "Boston Celtics"}]
    assert oa.match_game_to_event(game, events) == "y"
    swapped = [{"id": "z", "home_team": "Boston Celtics", "away_team": "New York Knicks"}]
    assert oa.match_game_to_event(game, swapped) == "z"
    assert oa.match_game_to_event(game, []) is None
    assert oa.match_game_to_event(game, [{"id": "w", "home_team": "Nowhere", "away_team": "Elsewhere"}]) is None
    assert oa._normalise_team("LA Clippers") == "LAC" and oa._normalise_team("the knicks squad") == "NYK"


def test_build_player_props_and_invalidate(fresh_cache):
    game = make_prop().game
    raw = [{"player_name": "Jane Doe", "market": "player_points", "line": 20.5, "over_odds": 1.9, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False},
           {"player_name": "Unknown", "market": "player_points", "line": 5.5, "over_odds": 1.9, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False},
           {"player_name": "Jane Doe", "market": "player_assists", "line": 5.5, "over_odds": 0.0, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False}]
    props = oa.build_player_props(raw, game, {"Jane Doe": 7})
    assert len(props) == 1 and props[0].nba_player_id == 7
    oa.cache_set("props_evt_x", [1]); oa.cache_set("other", [1])
    assert oa.invalidate_props_cache() == 1
