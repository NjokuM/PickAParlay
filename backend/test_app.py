import dataclasses
import sqlite3

import pytest

import config
from backend import app as A
from testkit import make_prop, make_vp
from src import cache, database
from src.analysis import results_checker
from src.api import injury_api, league_tables, nba_stats, odds_api
from src.models import NBAGame

def new_game():
    """A fresh game each time — the refresh writes odds_event_id onto it."""
    return NBAGame("0022600001", "BOS", "NYK", 1610612738, 1610612752, "2026-04-01", "2026-04-01T23:00:00Z", "")


GAME = new_game()


@pytest.fixture
def seeded(api, monkeypatch):
    """Today's scored props in the cache + graded rows in the DB."""
    vps = [make_vp(name=f"P{i}", pid=i, score=80 - 3 * i, home=["BOS", "MIA", "LAL"][i % 3],
                   away=["NYK", "CHI", "GSW"][i % 3], market=["player_points", "player_rebounds"][i % 2]) for i in range(6)]
    cache.save_scored_props([dataclasses.asdict(v) for v in vps])
    database.upsert_graded_props(vps, "2026-04-01")
    A.invalidate_props_cache()
    monkeypatch.setattr(A, "_props_response_cache", None)
    return vps


def test_health_and_tonight(api, monkeypatch):
    assert api.get("/health").json() == {"status": "ok"}
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda: [GAME, GAME])
    assert api.get("/api/tonight").json() == [{"game_id": GAME.game_id, "home_team": "BOS", "away_team": "NYK",
                                               "matchup": "NYK @ BOS", "game_date": "2026-04-01"}]


def test_props_filters_and_hit_fields(api, seeded):
    allp = api.get("/api/props").json()
    assert len(allp) == 6 and allp[0]["value_score"] >= allp[-1]["value_score"]
    assert allp[0]["hit_probability"] == 0.56 and allp[0]["is_special"] is False      # top-level fields present
    assert len(api.get("/api/props", params={"min_score": 70}).json()) == 4
    assert all("P0" == p["player_name"] for p in api.get("/api/props", params={"player": "p0"}).json())
    assert len(api.get("/api/props", params={"market": "Rebounds"}).json()) == 3
    assert len(api.get("/api/props", params={"game": "bos", "side": "OVER", "bookmaker": "fanduel"}).json()) == 2
    assert api.get("/api/bookmakers").json() == ["fanduel"]


def test_slips_build_and_save(api, seeded, user_headers):
    slips = api.get("/api/slips", params={"odds": "5/2", "min_score": 50}).json()
    assert slips and slips[0]["legs"]
    assert api.get("/api/slips", params={"odds": "garbage"}).status_code == 400
    assert api.get("/api/slips").status_code == 200
    saved = api.post("/api/slips/save", json={"odds": "5/2", "slip_index": 0, "min_score": 50}, headers=user_headers)
    assert saved.json()["saved"] is True
    assert api.post("/api/slips/save", json={"odds": "5/2", "slip_index": 99}, headers=user_headers).status_code == 404
    assert api.post("/api/slips/save", json={"odds": "x/y"}, headers=user_headers).status_code == 400
    assert api.post("/api/slips/save", json={}).status_code == 401


def test_slips_without_cache(api, user_headers):
    assert api.get("/api/slips").status_code == 404
    assert api.post("/api/slips/save", json={}, headers=user_headers).status_code == 404


def test_custom_slip_history_and_outcome(api, seeded, user_headers):
    ids = [r["id"] for r in database.get_prop_results(graded_only=False)][:2]
    r = api.post("/api/slips/custom", json={"leg_ids": ids}, headers=user_headers)
    assert r.status_code == 200
    assert api.post("/api/slips/custom", json={"leg_ids": []}, headers=user_headers).status_code == 400
    assert api.post("/api/slips/custom", json={"leg_ids": [99999]}, headers=user_headers).status_code == 404
    history = api.get("/api/history", headers=user_headers).json()
    assert len(history) == 1
    sid = history[0]["id"]
    assert api.patch(f"/api/history/{sid}/outcome", json={"outcome": "WIN", "stake": 10}, headers=user_headers).status_code == 200
    assert api.patch(f"/api/history/{sid}/outcome", json={"outcome": "MAYBE"}, headers=user_headers).status_code in (400, 422)


def test_results_analytics_versions_and_credits(api, seeded, monkeypatch):
    assert api.get("/api/prop-results", params={"graded_only": False}).json()
    assert api.get("/api/alt-props", params={"game_date": "2026-04-01"}).json() == []
    a = api.get("/api/analytics").json()
    assert "by_model_version" in a and "special_picks" in a
    assert api.get("/api/model-versions").json()["current"] == config.model_version_id()
    monkeypatch.setattr(config, "ODDS_API_KEYS", ["only"])
    monkeypatch.setattr(odds_api, "get_pool_credits", lambda: {"used": 1, "remaining": 2, "total": 3, "keys": [], "active_keys": 1, "total_keys": 1})
    monkeypatch.setattr(A, "get_pool_credits", odds_api.get_pool_credits)
    assert "remaining" in api.get("/api/credits").json()
    sched = api.get("/api/schedule").json()
    assert "jobs" in sched


def test_admin_triggers(api, admin_headers, user_headers, monkeypatch):
    ran = []
    monkeypatch.setattr(A, "_run_refresh_background", lambda s: ran.append("refresh"))
    monkeypatch.setattr(A, "_run_alt_refresh_background", lambda s: ran.append("alt"))
    monkeypatch.setattr(A, "_run_ladder_build_background", lambda s: ran.append("ladder"))
    monkeypatch.setattr(A, "_run_results_background", lambda d: ran.append("results"))
    monkeypatch.setattr(results_checker, "backfill_actuals", lambda a, b: {"filled": 0})
    assert api.post("/api/refresh", headers=admin_headers).json()["status"] == "started"
    assert api.post("/api/alt-refresh", headers=admin_headers).json()["status"] in ("started", "already_running")
    assert api.post("/api/ladder").status_code == 200
    assert api.post("/api/results/check", params={"game_date": "2026-04-01"}).status_code == 200
    assert api.post("/api/admin/backfill-actuals", headers=admin_headers).json()["status"] == "started"
    assert api.get("/api/admin/backfill-actuals", headers=admin_headers).status_code == 200
    assert api.post("/api/admin/backfill-actuals", headers=user_headers).status_code == 403
    for path in ("/api/refresh/status", "/api/alt-refresh/status", "/api/ladder/status", "/api/results/status"):
        assert api.get(path).status_code == 200
    assert api.get("/api/ladder/results").json() == []


def test_players_and_custom_grade(api, user_headers, offline_grading, monkeypatch):
    monkeypatch.setattr(nba_stats, "get_tonight_rosters", lambda: [{"player_name": "Jane Doe", "player_id": 7, "team": "BOS"}])
    assert api.get("/api/players", headers=user_headers).json()[0]["player_id"] == 7
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda: [new_game()])
    monkeypatch.setattr(odds_api, "get_events", lambda: [])
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: [])
    monkeypatch.setattr(nba_stats, "get_player_game_log_blended", lambda pid: offline_grading["log"])
    monkeypatch.setattr(nba_stats, "get_player_current_team", lambda pid: "BOS")
    body = {"player_name": "Jane Doe", "player_id": 7, "market": "player_points", "line": 20.5, "side": "over"}
    r = api.post("/api/grade-custom", json=body, headers=user_headers)
    assert r.status_code == 200 and r.json()["value_score"] > 0
    assert api.post("/api/grade-custom", json={**body, "side": "sideways"}, headers=user_headers).status_code == 400
    assert api.post("/api/grade-custom", json={**body, "market": "player_nonsense"}, headers=user_headers).status_code == 400


def test_custom_line_priced_from_market(api, seeded, monkeypatch):
    A._props_response_cache = None
    props = A._get_props_response()
    pid = props[0]["player_id"]
    p_low = A._custom_line_over_probability(pid, "player_points", 10.5)
    p_high = A._custom_line_over_probability(pid, "player_points", 35.5)
    assert p_low > p_high
    monkeypatch.setattr(nba_stats, "get_player_game_log_blended", lambda pid: __import__("pandas").DataFrame())
    assert A._custom_line_over_probability(12345, "player_points", 20.5) is None


def test_parse_odds():
    assert A._parse_odds("4/1") == 5.0 and A._parse_odds("2.5") == 2.5 and A._parse_odds("+150") == 2.5
    assert A._parse_odds("-200") == 1.5
    with pytest.raises((ValueError, ZeroDivisionError)):
        A._parse_odds("abc")


def test_full_refresh_pipeline_offline(api, offline_grading, monkeypatch):
    raw = [{"player_name": "Jane Doe", "market": "player_points", "line": 20.5, "over_odds": 1.9, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False}]
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda force_fresh=False: [new_game()])
    monkeypatch.setattr(odds_api, "invalidate_props_cache", lambda: 3)
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: [])
    monkeypatch.setattr(odds_api, "get_events", lambda: [{"id": "evt"}])
    monkeypatch.setattr(odds_api, "match_game_to_event", lambda g, e: "evt")
    monkeypatch.setattr(odds_api, "get_player_props_for_event", lambda eid, force_fresh=False: raw)
    monkeypatch.setattr(odds_api, "get_game_spread", lambda eid: -3.5)
    monkeypatch.setattr(nba_stats, "get_player_id", lambda name: 7)
    for fn in ("get_team_recent_form", "get_h2h_record", "get_opponent_defensive_profile", "get_player_game_log", "get_player_current_team"):
        monkeypatch.setattr(nba_stats, fn, lambda *a, **k: {})
    A._run_refresh_background("2026-27")
    state = api.get("/api/refresh/status").json()
    assert state["status"] == "done", state
    assert state["props_graded"] == 2 and set(state["timings"]) >= {"games", "grading", "save"}
    assert len(api.get("/api/props").json()) == 2
    with sqlite3.connect(config.DATABASE_PATH) as c:
        assert c.execute("SELECT COUNT(*) FROM refresh_snapshots").fetchone()[0] == 1


def test_refresh_with_no_games_or_props(api, monkeypatch):
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda force_fresh=False: [])
    A._run_refresh_background("2026-27")
    assert api.get("/api/refresh/status").json()["status"] == "no_games"
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda force_fresh=False: [new_game()])
    monkeypatch.setattr(odds_api, "invalidate_props_cache", lambda: 0)
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: [])
    monkeypatch.setattr(odds_api, "get_events", lambda: [])
    monkeypatch.setattr(odds_api, "match_game_to_event", lambda g, e: None)
    A._run_refresh_background("2026-27")
    st = api.get("/api/refresh/status").json(); assert st["status"] == "no_props", st["error"]
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: 1 / 0)
    A._run_refresh_background("2026-27")
    assert api.get("/api/refresh/status").json()["status"] == "error"


def test_results_background_and_schedulers(api, monkeypatch):
    monkeypatch.setattr(results_checker, "check_results_for_date", lambda d: {"checked": 2, "hit": 1, "miss": 1, "no_data": 0, "slips_resolved": 0})
    A._run_results_background("2026-04-01")
    assert api.get("/api/results/status").json()["checked"] == 2
    monkeypatch.setattr(results_checker, "check_results_for_date", lambda d: 1 / 0)
    A._run_results_background("2026-04-01")
    assert api.get("/api/results/status").json()["status"] == "error"
    ran = []
    monkeypatch.setattr(A, "_run_results_background", lambda d: ran.append(d))
    A._scheduled_grade_results()
    assert len(ran) == 2
    monkeypatch.setattr(A, "get_pool_credits", lambda: {"remaining": 10, "total_keys": 1})
    A._scheduled_refresh()                                   # skipped: too few credits
    monkeypatch.setattr(A, "get_pool_credits", lambda: {"remaining": 1000, "total_keys": 1})
    monkeypatch.setattr(A, "_run_refresh_background", lambda s: ran.append("refresh"))
    A._scheduled_refresh()
    import time; time.sleep(0.1)
    assert "refresh" in ran


def test_alt_refresh_and_ladder_offline(api, offline_grading, monkeypatch, seeded):
    raw = [{"player_name": "Jane Doe", "market": "player_points_alternate", "line": 15.5, "over_odds": 1.3, "under_odds": 3.2,
            "bookmaker": "fanduel", "is_paddy_power": False, "is_alternate": True}]
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda force_fresh=False: [new_game()])
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: [])
    monkeypatch.setattr(odds_api, "get_events", lambda: [{"id": "evt"}])
    monkeypatch.setattr(odds_api, "match_game_to_event", lambda g, e: "evt")
    monkeypatch.setattr(odds_api, "get_alternate_props_for_event", lambda eid: raw)
    monkeypatch.setattr(nba_stats, "get_player_id", lambda name: 7)
    monkeypatch.setattr(nba_stats, "get_player_game_log", lambda pid, season=None: offline_grading["log"])
    A._run_alt_refresh_background("2026-27")
    assert api.get("/api/alt-refresh/status").json()["status"] in ("done", "no_props")
    A._run_ladder_build_background("2026-27")
    assert api.get("/api/ladder/status").json()["status"] in ("done", "no_props", "no_slips", "error")
    assert isinstance(api.get("/api/ladder/results").json(), list)
