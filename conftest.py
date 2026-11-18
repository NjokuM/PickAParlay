"""
Shared test setup. Runs before any project module is imported, so config
picks up a throwaway database and cache — tests never touch real data —
and every outbound HTTP call fails unless a test stubs it.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="pickaparlay-tests-")
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CACHE_DIR"] = os.path.join(_TMP, "cache")
os.environ["ODDS_API_KEYS"] = "test-key-1,test-key-2"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["INVITE_CODE"] = "test-invite"
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
import requests  # noqa: E402

from testkit import build_log, make_prop, make_vp  # noqa: E402,F401


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any real HTTP request (requests, nba_api) fails loudly."""
    def blocked(*args, **kwargs):
        raise NetworkBlocked(f"network call in a test: {args[1:3] if len(args) > 1 else kwargs}")
    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """An empty, initialised database just for this test."""
    import config
    from src import database
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "db.sqlite"))
    database.init_db()
    return database


@pytest.fixture
def fresh_cache(monkeypatch, tmp_path):
    """An empty cache directory just for this test."""
    import config
    d = tmp_path / "cache"
    d.mkdir()
    monkeypatch.setattr(config, "CACHE_DIR", str(d))
    return d


@pytest.fixture
def make_log():
    return build_log


@pytest.fixture
def offline_grading(monkeypatch):
    """
    Stub every external lookup the grading pipeline makes (game logs, team
    form, spreads, injuries, league tables, priors) with small realistic
    data, so prop_grader/hit_scoring run end to end without the network.
    Returns a dict tests can tweak: log (the player's log), team, prior.
    """
    import pandas as pd
    from src.analysis import prop_grader, priors
    from src.analysis.factors import blowout_risk, injury_context, opponent_defense
    from src.api import league_tables

    state = {"log": build_log([24, 22, 26, 21, 25, 23, 27, 20, 24, 22]), "team": "BOS",
             "prior": {"GP": 60, "MPG": 30.0, "rates": {s: 0.7 for s in ("PTS", "REB", "AST", "FG3M", "PRA", "PR", "PA", "RA")}}}
    monkeypatch.setattr(prop_grader, "get_player_game_log_blended", lambda pid, season=None: state["log"].copy())
    monkeypatch.setattr(prop_grader, "get_player_current_team", lambda pid: state["team"])
    monkeypatch.setattr(prop_grader, "get_team_recent_form", lambda *a, **k: {"wins": 3, "losses": 2, "back_to_back": False})
    monkeypatch.setattr(prop_grader, "get_h2h_record", lambda *a, **k: {"wins": 1, "losses": 1, "avg_margin": 2.0, "games": 2})
    monkeypatch.setattr(prop_grader, "get_game_spread", lambda eid: -4.5)
    monkeypatch.setattr(priors, "get_player_prior", lambda pid, season=None: state["prior"])
    monkeypatch.setattr(opponent_defense, "get_opponent_defensive_profile", lambda *a, **k: {
        "TEAM_NAME": "New York Knicks", "OPP_PTS": 112.0, "OPP_PTS_pct": 0.5, "OPP_REB": 44.0, "OPP_REB_pct": 0.5,
        "OPP_AST": 25.0, "OPP_AST_pct": 0.5, "OPP_FG3M": 13.0, "OPP_FG3M_pct": 0.5, "PACE": 100.0,
        "PACE_pct": 0.5, "DEF_RATING": 112.0, "GP": 40, "PRIOR_GAMES": 0.0})
    monkeypatch.setattr(blowout_risk, "get_team_avg_win_margin", lambda *a, **k: 8.0)
    monkeypatch.setattr(injury_context, "get_league_player_usage", lambda: {})
    league = pd.DataFrame({"TEAM_ABBREVIATION": ["BOS"] * 6, "PLAYER_ID": [1, 2] * 3, "PLAYER_NAME": ["A B", "C D"] * 3,
                           "GAME_ID": ["G1", "G1", "G2", "G2", "G3", "G3"], "GAME_DATE": ["2026-03-01"] * 2 + ["2026-03-03"] * 2 + ["2026-03-05"] * 2,
                           "MIN": 30.0, "PTS": 10.0, "REB": 5.0, "AST": 3.0, "FG3A": 4.0, "FG3M": 1.0, "FGA": 10.0})
    monkeypatch.setattr(league_tables, "get_league_player_log", lambda season: league)
    monkeypatch.setattr(league_tables, "get_snapshot", lambda season: {})
    return state


@pytest.fixture
def prop_factory():
    return make_prop


@pytest.fixture
def vp_factory():
    return make_vp


@pytest.fixture
def api(fresh_db, fresh_cache, monkeypatch):
    """FastAPI test client on an empty database. Startup hooks (scheduler) don't run."""
    from fastapi.testclient import TestClient
    from backend import auth
    from backend.app import app
    monkeypatch.setattr(auth, "_HASH_ITERATIONS", 1000)         # fast hashing in tests
    return TestClient(app)


@pytest.fixture
def admin_headers(api):
    """Register the first user (auto-admin) and return auth headers."""
    from backend import auth
    r = api.post("/api/auth/register", json={"username": "admin", "password": "secret1", "invite_code": auth.INVITE_CODE})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def user_headers(api, admin_headers):
    """A second, non-admin user."""
    from backend import auth
    r = api.post("/api/auth/register", json={"username": "punter", "password": "secret1", "invite_code": auth.INVITE_CODE})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
