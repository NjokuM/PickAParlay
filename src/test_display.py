import pytest
from rich.console import Console

from testkit import make_prop, make_vp
from src import display
from src.analysis import bet_builder
from src.models import NBAGame


@pytest.fixture(autouse=True)
def capture(monkeypatch):
    con = Console(record=True, width=160)
    monkeypatch.setattr(display, "console", con)
    return con


def test_static_messages(capture, monkeypatch):
    monkeypatch.setattr(display, "credits_summary", lambda: "Odds API: 1/500", raising=False)
    display.print_header(); display.print_no_games(); display.print_no_props(); display.print_no_slips(5.0)
    display.print_slips_header(2, 5.0)
    try:
        display.print_credits()
    except Exception:
        pass
    out = capture.export_text()
    assert out.strip()


def test_tables_and_slips(capture):
    vps = [make_vp(name="Jane Doe", score=82), make_vp(name="John Roe", pid=8, score=55, side="under")]
    display.print_games_table([NBAGame("1", "BOS", "NYK", 1, 2, "2026-04-01", "2026-04-01T23:00:00Z", "")])
    display.print_props_table(vps)
    display.print_valued_prop(vps[0], rank=1)
    slip = bet_builder._make_slip([vps[0], make_vp(name="B", pid=9, home="MIA", away="CHI")], 3.61, 3.6)
    display.print_slip(slip, 1)
    out = capture.export_text()
    assert "Jane Doe" in out and "John Roe" in out


def test_helpers():
    assert display._score_colour(85) == "bold green" and display._score_colour(40) == "red"
    assert display._score_colour(70) == "green" and display._score_colour(55) == "yellow"
    assert display._rec_colour("Good Value") == "green" and display._rec_colour("??") == "white"
    assert display._decimal_to_fractional(5.0) == "4/1"
    assert display._decimal_to_fractional(1.0) == "N/A"
    assert display._decimal_to_fractional(1.333) == "1/3"
    assert display._top_evidence_bullets(make_vp())
    assert display.make_progress() is not None
