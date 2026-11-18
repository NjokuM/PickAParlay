import dataclasses

import pytest
from click.testing import CliRunner

import main
from testkit import make_vp
from src import cache, database
from src.api import injury_api, nba_stats, odds_api
from src.models import NBAGame


def new_game():
    return NBAGame("0022600001", "BOS", "NYK", 1610612738, 1610612752, "2026-04-01", "2026-04-01T23:00:00Z", "")


@pytest.fixture
def offline_cli(offline_grading, fresh_db, fresh_cache, monkeypatch):
    raw = [{"player_name": "Jane Doe", "market": "player_points", "line": 20.5, "over_odds": 1.9, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False},
           {"player_name": "John Roe", "market": "player_rebounds", "line": 6.5, "over_odds": 1.9, "under_odds": 1.9,
            "bookmaker": "fanduel", "is_paddy_power": False}]
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda *a, **k: [new_game()])
    monkeypatch.setattr(injury_api, "get_injury_report", lambda: [])
    monkeypatch.setattr(odds_api, "get_events", lambda: [{"id": "evt"}])
    monkeypatch.setattr(odds_api, "match_game_to_event", lambda g, e: "evt")
    monkeypatch.setattr(odds_api, "get_player_props_for_event", lambda *a, **k: raw)
    monkeypatch.setattr(nba_stats, "get_player_id", lambda name: 7 if name == "Jane Doe" else 8)
    monkeypatch.setattr(main.display, "print_credits", lambda: None)
    return CliRunner()


def test_parse_odds():
    assert main.parse_odds("4/1") == 5.0 and main.parse_odds("3.5") == 3.5
    assert main.parse_odds("+200") == 3.0 and main.parse_odds("-200") == 1.5
    with pytest.raises(Exception):
        main.parse_odds("abc")


def test_refresh_command_grades_caches_and_saves(offline_cli):
    r = offline_cli.invoke(main.cli, ["refresh"])
    assert r.exit_code == 0, r.output
    assert len(cache.load_scored_props_raw()) == 4
    assert database.get_latest_run_id() is not None
    assert len(database.get_prop_results(graded_only=False)) == 4


def test_refresh_with_no_games(offline_cli, monkeypatch):
    monkeypatch.setattr(nba_stats, "get_todays_games", lambda *a, **k: [])
    assert offline_cli.invoke(main.cli, ["refresh"]).exit_code == 0
    assert cache.load_scored_props_raw() is None


def test_slips_command_uses_cache(offline_cli):
    assert "refresh" in offline_cli.invoke(main.cli, ["slips", "--odds", "3/1"]).output.lower()
    vps = [make_vp(name=f"P{i}", pid=i, score=80 - i, home=["BOS", "MIA", "LAL"][i % 3], away=["NYK", "CHI", "GSW"][i % 3])
           for i in range(6)]
    cache.save_scored_props([dataclasses.asdict(v) for v in vps])
    r = offline_cli.invoke(main.cli, ["slips", "--odds", "5/2", "--legs", "2", "--min-score", "50"])
    assert r.exit_code == 0, r.output


def test_root_command_runs_pipeline(offline_cli):
    r = offline_cli.invoke(main.cli, ["--odds", "5/2", "--min-score", "0"])
    assert r.exit_code == 0, r.output


def test_history_command(offline_cli):
    assert offline_cli.invoke(main.cli, ["history"]).exit_code == 0
    from src.analysis import bet_builder
    slip = bet_builder._make_slip([make_vp(name="A", pid=1), make_vp(name="B", pid=2, home="MIA", away="CHI")], 3.61, 3.6)
    database.save_slip(slip, "5/2")
    r = offline_cli.invoke(main.cli, ["history", "--limit", "5"])
    assert r.exit_code == 0 and "5/2" in r.output


def test_vp_roundtrip_and_legs_summary():
    vp = make_vp()
    back = main._vp_from_dict(dataclasses.asdict(vp))
    assert back.prop.player_name == vp.prop.player_name and back.factors[0].name == "Consistency"
    assert main._legs_summary([{"player_name": "A", "side": "over", "line": 1.5, "market_label": "Points"}])


def test_history_shows_overall_record_and_pnl(offline_cli):
    from src.analysis import bet_builder
    slip = bet_builder._make_slip([make_vp(name="A", pid=1), make_vp(name="B", pid=2, home="MIA", away="CHI")], 3.61, 3.6)
    sid = database.save_slip(slip, "5/2")
    database.record_outcome(sid, "WIN", stake=10)
    r = offline_cli.invoke(main.cli, ["history"])
    assert "1/1 wins" in r.output and "P&L" in r.output


def test_slips_save_below_threshold_and_verbose(offline_cli):
    vps = [make_vp(name=f"P{i}", pid=i, score=80 - i, home=["BOS", "MIA", "LAL"][i % 3], away=["NYK", "CHI", "GSW"][i % 3])
           for i in range(6)]
    cache.save_scored_props([dataclasses.asdict(v) for v in vps])
    saved = offline_cli.invoke(main.cli, ["slips", "--odds", "5/2", "--legs", "2", "--save", "--verbose"])
    assert saved.exit_code == 0 and "saved to database" in saved.output
    none = offline_cli.invoke(main.cli, ["slips", "--odds", "5/2", "--min-score", "99"])
    assert "No props met the minimum score" in none.output
    nothing = offline_cli.invoke(main.cli, ["slips", "--odds", "500/1", "--save"])
    assert nothing.exit_code == 0
