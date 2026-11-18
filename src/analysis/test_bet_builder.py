import pytest

from testkit import make_vp
from src.analysis import bet_builder as bb


def pool():
    # 6 players in 3 games, odds ~1.9 each
    return [make_vp(name=f"P{i}", pid=i, score=80 - i, home=["BOS", "MIA", "LAL"][i % 3], away=["NYK", "CHI", "GSW"][i % 3])
            for i in range(6)]


def test_slips_land_near_target_odds():
    slips = bb.build_slips(pool(), target_decimal=3.6)
    assert slips and all(len(s.legs) >= 2 for s in slips)
    best = slips[0]
    assert abs(best.combined_decimal_odds - 3.6) / 3.6 <= 0.25
    assert best.summary and best.total_value_score > 0


def test_fixed_leg_count_and_forced_counts():
    assert all(len(s.legs) == 3 for s in bb.build_slips(pool(), target_decimal=6.9, n_legs=3))
    assert all(len(s.legs) in (2, 3) for s in bb.build_slips(pool(), target_decimal=5.0, force_leg_counts=[2, 3], tolerance=0.5))


def test_best_value_mode_without_target():
    slips = bb.build_slips(pool(), target_decimal=None, n_legs=2)
    assert slips and slips[0].target_decimal_odds is None


def test_filters():
    assert bb.build_slips(pool(), target_decimal=3.6, min_score=99) == []
    assert bb.build_slips(pool(), target_decimal=3.6, bookmaker="paddypower") == []
    assert bb.build_slips(pool(), target_decimal=3.6, bookmaker="fanduel")


def test_helpers():
    vp_over, vp_under = make_vp(odds=2.0, under_odds=1.7), make_vp(odds=2.0, under_odds=1.7, side="under")
    assert bb._prop_decimal_odds(vp_over) == 2.0 and bb._prop_decimal_odds(vp_under) == 1.7
    same_player_overlap = (make_vp(market="player_points"), make_vp(market="player_points_rebounds"))
    assert bb._has_overlapping_markets(same_player_overlap)
    assert not bb._has_overlapping_markets((make_vp(name="A", pid=1), make_vp(name="B", pid=2)))
    slip = bb._make_slip([make_vp(name="A", pid=1), make_vp(name="B", pid=2)], 3.61, 3.6)
    assert slip.has_correlated_legs                 # both legs from BOS @ NYK
    assert bb._slip_player_set(slip) == {"A", "B"}
    assert bb._estimate_leg_counts(pool(), 3.6)
