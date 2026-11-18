import sqlite3

import pandas as pd
import pytest

import config
from testkit import make_vp
from src.analysis import results_checker as rc


class FakeScoreboard:
    def __init__(self, game_date, league_id="00"):
        games = pd.DataFrame({"gameId": ["G1"], "gameStatus": [3]})
        self.data_sets = [type("DS", (), {"get_data_frame": lambda s, df=df: df})() for df in (pd.DataFrame(), games)]


class FakeBox:
    def __init__(self, game_id):
        self.game_id = game_id

    def get_dict(self):
        def player(first, last, pts, reb, ast, minutes="31:30"):
            return {"firstName": first, "familyName": last,
                    "statistics": {"points": pts, "reboundsTotal": reb, "assists": ast, "threePointersMade": 2,
                                   "minutes": minutes}}
        return {"boxScoreTraditional": {
            "homeTeam": {"players": [player("Jane", "Doe", 25, 8, 5), player("Derrick", "Jones Jr.", 10, 4, 1)]},
            "awayTeam": {"players": [player("Nikola", "Jokić", 30, 12, 10, "PT36M00.00S")]}}}


@pytest.fixture
def nba(monkeypatch):
    import nba_api.stats.endpoints as ep
    from nba_api.stats.endpoints import boxscoretraditionalv3
    monkeypatch.setattr(ep, "ScoreboardV3", FakeScoreboard)
    monkeypatch.setattr(boxscoretraditionalv3, "BoxScoreTraditionalV3", FakeBox)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)


def test_parse_minutes():
    assert rc._parse_minutes("31:30") == 31.5
    assert rc._parse_minutes("PT36M00.00S") == 36.0
    assert rc._parse_minutes(None) is None and rc._parse_minutes("bad") is None


def test_box_scores_and_name_matching(nba):
    stats = rc.fetch_box_scores("2026-03-01")
    assert stats["derrick jones"]["points"] == 10          # suffix stripped
    assert rc.actual_stat("Nikola Jokic", "player_points_rebounds_assists", stats) == (52.0, 36.0)
    assert rc.actual_stat("Derrick Jones", "player_points_alternate", stats)[0] == 10
    assert rc.actual_stat("Nobody", "player_points", stats) is None
    assert rc.actual_stat("Jane Doe", "player_steals_xyz", stats) is None


def test_check_leg():
    stats = {"jane doe": {"points": 25.0}}
    assert rc.check_leg("Jane Doe", "player_points", 20.5, "over", stats) == "HIT"
    assert rc.check_leg("Jane Doe", "player_points", 20.5, "under", stats) == "MISS"
    assert rc.check_leg("Ghost", "player_points", 20.5, "over", stats) is None


def test_scoreboard_retries_then_gives_up(monkeypatch):
    import nba_api.stats.endpoints as ep
    calls = []
    def boom(**kw):
        calls.append(1); raise TimeoutError("throttled")
    monkeypatch.setattr(ep, "ScoreboardV3", boom)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    assert rc.fetch_game_info_for_date("03/01/2026") == [] and len(calls) == 3


def test_check_results_records_hits_and_actuals(nba, fresh_db):
    fresh_db.upsert_graded_props([make_vp(name="Jane Doe", line=20.5), make_vp(name="Jane Doe", line=20.5, side="under"),
                                  make_vp(name="Missing Man", pid=9)], "2026-03-01")
    summary = rc.check_results_for_date("2026-03-01")
    assert summary["hit"] == 1 and summary["miss"] == 1 and summary["no_data"] == 1
    with sqlite3.connect(config.DATABASE_PATH) as c:
        rows = c.execute("SELECT side, leg_result, actual_value, actual_minutes FROM graded_props WHERE player_name='Jane Doe'").fetchall()
    assert sorted(rows) == [("over", "HIT", 25.0, 31.5), ("under", "MISS", 25.0, 31.5)]


def test_backfill_actuals(nba, fresh_db):
    fresh_db.upsert_graded_props([make_vp(name="Jane Doe")], "2026-03-01")
    with sqlite3.connect(config.DATABASE_PATH) as c:
        c.execute("UPDATE graded_props SET leg_result='HIT'")
    assert rc.backfill_actuals("2026-03-01", "2026-03-01") == {"dates": 1, "filled": 1, "not_found": 0}
    assert rc.backfill_actuals() == {"dates": 0, "filled": 0, "not_found": 0}
