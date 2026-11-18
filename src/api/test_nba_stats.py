from datetime import datetime, timedelta

import pandas as pd
import pytest

import config
from src.api import nba_stats as ns


class DS:
    def __init__(self, df):
        self.df = df

    def get_data_frame(self):
        return self.df.copy()


def fake(*frames, normalized=None, fail=False):
    """A stand-in nba_api endpoint class returning `frames` in every access style."""
    class Endpoint:
        calls = []

        def __init__(self, **kw):
            if fail:
                raise TimeoutError("nba api down")
            Endpoint.calls.append(kw)
            self.data_sets = [DS(f) for f in frames]

        def get_data_frames(self):
            return [f.copy() for f in frames]

        def get_normalized_dict(self):
            return normalized or {}

        def __getattr__(self, name):          # player_game_log, team_game_log, common_team_roster, …
            return DS(frames[0])
    return Endpoint


@pytest.fixture(autouse=True)
def isolate(monkeypatch, fresh_cache):
    for memo in ("_log_memo", "_team_table_memo", "_profile_memo"):
        monkeypatch.setattr(ns, memo, {})
    monkeypatch.setattr(config, "is_playoffs", lambda: False)


def pgl(n=6, start="2026-03-20"):
    dates = pd.date_range(end=start, periods=n, freq="2D")[::-1]
    return pd.DataFrame({"Game_ID": [f"G{i}" for i in range(n)], "GAME_DATE": dates.strftime("%b %d, %Y"),
                         "MATCHUP": ["BOS vs. NYK"] * n, "MIN": [30] * n, "PTS": [20] * n, "REB": [5] * n, "AST": [4] * n})


def test_game_data_ttl_is_time_since_6am_utc():
    ttl = ns.game_data_ttl()
    assert 60 <= ttl <= 24 * 3600


def test_player_game_log_fetch_memo_and_ot_flags(monkeypatch):
    monkeypatch.setattr(ns, "PlayerGameLog", fake(pgl()))
    monkeypatch.setattr(ns, "LeagueGameLog", fake(pd.DataFrame({"GAME_ID": ["G0", "G0", "G1"], "MIN": [265, 265, 240]})))
    df = ns.get_player_game_log(7)
    assert list(df.columns[-5:]) and df.PRA.iloc[0] == 29 and bool(df.IS_OT.iloc[0]) and not df.IS_OT.iloc[1]
    monkeypatch.setattr(ns, "PlayerGameLog", fake(fail=True))
    assert len(ns.get_player_game_log(7)) == 6                 # served from memory
    ns._log_memo.clear()
    assert len(ns.get_player_game_log(7)) == 6                 # served from the file cache
    assert ns.get_player_game_log(8).empty                     # fetch failure → empty


def test_blended_log_regular_and_playoffs(monkeypatch):
    monkeypatch.setattr(ns, "PlayerGameLog", fake(pgl()))
    monkeypatch.setattr(ns, "LeagueGameLog", fake(pd.DataFrame({"GAME_ID": [], "MIN": []})))
    rs = ns.get_player_game_log_blended(7)
    assert (rs.PLAYOFF_WEIGHT == 1.0).all()
    monkeypatch.setattr(config, "is_playoffs", lambda: True)
    ns._log_memo.clear()
    both = ns.get_player_game_log_blended(9)
    assert both.IS_PLAYOFF_GAME.any() and both.PLAYOFF_WEIGHT.max() == config.PLAYOFF_GAME_WEIGHT
    assert ns.get_player_game_log_prev_season(7) is not None


def test_todays_games_skips_started_games(monkeypatch):
    header = pd.DataFrame({"gameId": ["1", "2", "3"], "gameStatus": [1, 2, 1], "gameCode": ["20260401/NYKBOS", "20260401/MIACHI", "bad"],
                           "gameTimeUTC": ["2026-04-01T23:00:00Z"] * 3})
    teams = pd.DataFrame({"gameId": ["1", "1"], "teamId": [1610612752, 1610612738], "teamTricode": ["NYK", "BOS"]})
    monkeypatch.setattr(ns, "ScoreboardV3", fake(pd.DataFrame(), header, teams))
    games = ns.get_todays_games(force_fresh=True)
    assert [(g.away_team, g.home_team) for g in games] == [("NYK", "BOS")]
    assert ns.get_todays_games()[0].home_team_id == 1610612738          # cached
    monkeypatch.setattr(ns, "ScoreboardV3", fake(fail=True))
    assert ns.get_todays_games(force_fresh=True) == []


def test_roster_lookups(monkeypatch):
    roster = pd.DataFrame({"DISPLAY_FIRST_LAST": ["Cameron Boozer", "Herbert Jones", "Derrick Jones Jr."],
                           "PERSON_ID": [1643409, 1630529, 1627884], "TEAM_ABBREVIATION": ["MEM", "NOP", "LAC"]})
    monkeypatch.setattr(ns, "CommonAllPlayers", fake(roster))
    assert ns.get_player_id("Cameron Boozer") == 1643409
    assert ns.get_player_id("Herb Jones") == 1630529
    assert ns.get_player_id("Derrick Jones") == 1627884
    assert ns.get_player_id("Zzzz Nobody") is None
    assert ns.get_player_current_team(1643409) == "MEM"


def test_current_team_falls_back_to_player_info(monkeypatch):
    monkeypatch.setattr(ns, "CommonAllPlayers", fake(fail=True))
    monkeypatch.setattr(ns, "CommonPlayerInfo", fake(pd.DataFrame(), normalized={"CommonPlayerInfo": [{"TEAM_ABBREVIATION": "bos"}]}))
    assert ns.get_player_current_team(5) == "BOS"
    assert ns.get_player_current_team(5) == "BOS"            # cached
    monkeypatch.setattr(ns, "CommonPlayerInfo", fake(fail=True))
    assert ns.get_player_current_team(6) is None
    assert ns.get_player_id("Jayson Tatum") == 1628369         # static list fallback


def test_static_team_helpers():
    assert ns.get_team_id("BOS") == 1610612738 and ns.get_team_id("XXX") is None
    assert ns.get_team_abbreviation("Celtics") == "BOS" and ns.get_team_abbreviation("qqqqqq") is None
    assert ns._team_id_to_abbr(1610612738) == "BOS" and ns._team_id_to_abbr(1) is None
    assert ns._game_has_started({"GAME_STATUS_ID": "2"}, datetime.now())
    assert ns._parse_minutes("38:30") == 38.5 and ns._parse_minutes(12) == 12.0 and ns._parse_minutes("x") == 0.0


def test_season_averages_and_league_totals(monkeypatch):
    monkeypatch.setattr(ns, "PlayerGameLog", fake(pgl()))
    monkeypatch.setattr(ns, "LeagueGameLog", fake(pd.DataFrame({"GAME_ID": [], "MIN": []})))
    assert ns.get_player_season_averages(7)["PTS"] == 20 and ns.get_player_season_averages(7)["GP"] == 6
    totals = pd.DataFrame({"PLAYER_ID": [1], "GP": [70], "MIN": [2100], "PTS": [1400], "REB": [400], "AST": [300], "FG3M": [100], "X": [0]})
    monkeypatch.setattr(ns, "LeagueDashPlayerStats", fake(totals))
    assert list(ns.get_league_player_totals("2025-26").columns) == ["PLAYER_ID", "GP", "MIN", "PTS", "REB", "AST", "FG3M"]
    monkeypatch.setattr(ns, "LeagueDashPlayerStats", fake(fail=True))
    assert ns.get_league_player_totals("2024-25").empty


TEAM_IDS = [1610612738, 1610612752, 1610612748]


def team_tables(gp):
    opp = pd.DataFrame({"TEAM_ID": TEAM_IDS, "TEAM_NAME": ["Celtics", "Knicks", "Heat"], "GP": [gp] * 3,
                        "OPP_PTS": [110 * gp, 120 * gp, 100 * gp], "OPP_AST": [25 * gp] * 3, "OPP_REB": [44 * gp] * 3, "OPP_FG3M": [12 * gp] * 3})
    adv = pd.DataFrame({"TEAM_ID": TEAM_IDS, "PACE": [99.0, 102.0, 97.0], "DEF_RATING": [110.0, 118.0, 105.0]})
    return opp, adv


def test_opponent_profile_blends_last_season(monkeypatch):
    cur, prev = team_tables(5), team_tables(82)
    def defensive(season): return (cur if season == "2026-27" else prev)[0]
    def advanced(season): return (cur if season == "2026-27" else prev)[1]
    monkeypatch.setattr(ns, "get_team_defensive_stats", defensive)
    monkeypatch.setattr(ns, "get_team_advanced_stats", advanced)
    p = ns.get_opponent_defensive_profile(1610612752, season="2026-27")
    assert p["TEAM_NAME"] == "Knicks" and p["GP"] == 5 and p["PRIOR_GAMES"] > 0
    assert p["OPP_PTS_pct"] > 0.5 and p["PACE"] == 102.0
    assert ns.get_opponent_defensive_profile(999, season="2026-27") is None
    assert ns.team_prior_weight(0) == config.TEAM_PRIOR_GAMES and ns.team_prior_weight(1000) == 0


def test_opponent_profile_without_current_season(monkeypatch):
    prev = team_tables(82)
    monkeypatch.setattr(ns, "get_team_defensive_stats", lambda s: prev[0] if s != "2026-27" else pd.DataFrame())
    monkeypatch.setattr(ns, "get_team_advanced_stats", lambda s: prev[1] if s != "2026-27" else pd.DataFrame())
    assert ns.get_opponent_defensive_profile(1610612738, season="2026-27")["GP"] == 0
    monkeypatch.setattr(ns, "get_team_defensive_stats", lambda s: pd.DataFrame())
    ns._team_table_memo.clear(); ns._profile_memo.clear()
    assert ns.get_opponent_defensive_profile(1610612738, season="2026-27") is None


def test_team_stat_endpoints(monkeypatch):
    monkeypatch.setattr(ns, "LeagueDashTeamStats", fake(team_tables(10)[0]))
    assert len(ns.get_team_defensive_stats("2026-27")) == 3 and len(ns.get_team_advanced_stats("2026-27")) == 3
    monkeypatch.setattr(ns, "LeagueDashTeamStats", fake(fail=True))
    assert ns.get_team_defensive_stats("2024-25").empty and ns.get_team_advanced_stats("2024-25").empty


def team_log():
    today = datetime.now(ns._ET).date()
    dates = [today - timedelta(days=d) for d in (1, 3, 5, 7, 9, 11)]
    return pd.DataFrame({"GAME_DATE": [d.strftime("%b %d, %Y") for d in dates], "WL": ["W", "W", "L", "W", "L", "L"],
                         "MATCHUP": ["BOS vs. NYK", "BOS @ MIA", "BOS @ NYK", "BOS vs. CHI", "BOS vs. NYK", "BOS @ LAL"],
                         "PLUS_MINUS": [10, 4, -6, 20, -3, -8]})


def test_team_form_h2h_and_margin(monkeypatch):
    monkeypatch.setattr(ns, "TeamGameLog", fake(team_log()))
    form = ns.get_team_recent_form(1610612738)
    assert form["wins"] == 3 and form["back_to_back"] is True and form["streak"] == "W2"
    assert ns.get_team_recent_form(1610612738) == form          # cached
    h2h = ns.get_h2h_record(1610612738, "NYK")
    assert h2h["games"] == 3 and h2h["wins"] == 1
    assert ns.get_h2h_record(1610612738, "GSW")["games"] == 0
    assert ns.get_team_avg_win_margin(1610612738) == pytest.approx((10 + 4 + 20) / 3, abs=0.1)
    assert ns._compute_streak([]) == "N/A" and ns._compute_streak(["L", "L", "W"]) == "L2"


def test_team_log_failures(monkeypatch):
    monkeypatch.setattr(ns, "TeamGameLog", fake(fail=True))
    assert ns.get_team_recent_form(1)["wins"] == 0
    assert ns.get_h2h_record(2, "NYK")["games"] == 0
    assert ns.get_team_avg_win_margin(3) == 0.0


def test_rosters_and_usage(monkeypatch):
    monkeypatch.setattr(ns, "get_todays_games", lambda: [ns.NBAGame("1", "BOS", "NYK", 1610612738, 1610612752, "2026-04-01", "", "")])
    monkeypatch.setattr(ns, "CommonTeamRoster", fake(pd.DataFrame({"PLAYER": ["B Two", "A One"], "PLAYER_ID": [2, 1]})))
    players = ns.get_tonight_rosters()
    assert [p["player_name"] for p in players][:2] == ["A One", "A One"]
    assert ns.get_tonight_rosters() == players
    usage = pd.DataFrame({"PLAYER_NAME": ["Jane Doe", ""], "MIN": [32.0, 5.0], "FGA": [15.0, 1.0], "USG_PCT": [0.25, 0.1]})
    monkeypatch.setattr(ns, "LeagueDashPlayerStats", fake(usage))
    assert ns.get_league_player_usage() == {"jane doe": {"mpg": 32.0, "fga": 15.0, "usg_pct": 25.0}}
    monkeypatch.setattr(ns, "get_todays_games", lambda: [])
    assert ns.get_tonight_rosters() == []
