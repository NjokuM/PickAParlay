import json
import sqlite3

import numpy as np
import pytest

import config
from testkit import make_vp
from src import database as db
from src.analysis import bet_builder
from src.models import FactorResult, InjuryReport


def rows(sql, *params):
    with sqlite3.connect(config.DATABASE_PATH) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, params)]


def grade_night(fresh_db, date="2026-04-01"):
    vps = [make_vp(name="Jane Doe", score=72), make_vp(name="Jane Doe", score=40, side="under"),
           make_vp(name="John Roe", pid=8, score=66, market="player_rebounds", line=8.5),
           make_vp(name="John Roe", pid=8, score=45, market="player_rebounds", line=8.5, side="under")]
    ids = fresh_db.upsert_graded_props(vps, date)
    fresh_db.finalize_graded_props(date, ids)
    return ids


def test_init_is_idempotent_and_registers_versions(fresh_db):
    fresh_db.init_db()
    versions = [v["version"] for v in fresh_db.get_model_versions()]
    assert config.LEGACY_MODEL_VERSION in versions and config.model_version_id() in versions


def test_upsert_stamps_version_and_factor_details(fresh_db):
    ids = grade_night(fresh_db)
    r = rows("SELECT * FROM graded_props WHERE id = ?", ids[0])[0]
    assert r["model_version"] == config.model_version_id()
    assert json.loads(r["factors_json"])[0]["name"] == "Consistency"
    assert r["hit_prob"] == 0.56 and r["is_special"] == 0
    # re-grading returns the same ids (RETURNING, not stale lastrowid)
    again = fresh_db.upsert_graded_props([make_vp(name="Jane Doe", score=75)], "2026-04-01", mark_stale=False)
    assert again == [ids[0]]


def test_best_side_and_stale_marking_scoped_to_games(fresh_db):
    ids = grade_night(fresh_db)
    best = rows("SELECT player_name, side FROM graded_props WHERE is_best_side = 1 ORDER BY player_name")
    assert best == [{"player_name": "Jane Doe", "side": "over"}, {"player_name": "John Roe", "side": "over"}]
    # a late refresh covering another game must not deactivate these
    late = fresh_db.upsert_graded_props([make_vp(name="Late Guy", pid=9, home="LAL", away="GSW")], "2026-04-01", mark_stale=False)
    fresh_db.finalize_graded_props("2026-04-01", late)
    assert rows("SELECT COUNT(*) n FROM graded_props WHERE is_active = 1")[0]["n"] == 5
    # a refresh of the same game without John Roe deactivates him
    fresh_db.finalize_graded_props("2026-04-01", ids[:2])
    assert {r["player_name"] for r in rows("SELECT player_name FROM graded_props WHERE is_active = 0")} == {"John Roe"}
    assert fresh_db.repair_deactivated_regular_props() == 2
    fresh_db.finalize_graded_props("2026-04-01", [])


def test_lookups(fresh_db):
    ids = grade_night(fresh_db)
    assert fresh_db.get_graded_prop_id("Jane Doe", "player_points", 20.5, "over", "2026-04-01") == ids[0]
    assert fresh_db.get_graded_prop_id("Nobody", "player_points", 1, "over", "2026-04-01") is None
    assert len(fresh_db.get_all_graded_prop_ids("2026-04-01")) == 4
    assert [r["id"] for r in fresh_db.get_graded_props_by_ids(ids[:2])] == ids[:2]
    assert fresh_db.get_graded_props_by_ids([]) == []


def test_results_actuals_and_prop_results(fresh_db):
    ids = grade_night(fresh_db)
    assert len(fresh_db.get_unresolved_graded_props("2026-04-01")) == 4
    fresh_db.record_graded_prop_result(ids[0], "HIT", actual_value=25, actual_minutes=33.5)
    fresh_db.record_graded_prop_result(ids[2], "MISS")
    assert fresh_db.get_dates_missing_actuals() == ["2026-04-01"]
    missing = fresh_db.get_graded_props_missing_actuals("2026-04-01")
    fresh_db.set_graded_prop_actual(missing[0]["id"], 7.0, 30.0)
    assert fresh_db.get_dates_missing_actuals() == []
    res = fresh_db.get_prop_results(date_from="2026-04-01", date_to="2026-04-01", result="HIT", side="over",
                                    market="Points", player="Jane", min_score=50, picks_only=True, active_only=True)
    assert len(res) == 1 and res[0]["actual_value"] == 25
    assert len(fresh_db.get_prop_results(graded_only=False, alt_filter="all")) == 4
    assert fresh_db.get_prop_results(alt_filter="alt") == []


def test_slips_outcomes_and_history(fresh_db):
    grade_night(fresh_db)
    run_id = fresh_db.save_grading_run("2026-27", 1, 4, 4, 2)
    assert fresh_db.get_latest_run_id() == run_id
    slip = bet_builder._make_slip([make_vp(name="Jane Doe"), make_vp(name="John Roe", pid=8, market="player_rebounds", line=8.5)], 3.61, 3.6)
    sid = fresh_db.save_slip(slip, "5/2", run_id=run_id, user_id=None)
    history = fresh_db.get_history()
    assert history[0]["id"] == sid and len(history[0]["legs"]) == 2
    leg_ids = [l["id"] for l in history[0]["legs"]]
    for l in history[0]["legs"]:
        fresh_db.record_leg_result(l["id"], "HIT")
    assert fresh_db.auto_resolve_slip_outcome(sid) == "WIN"
    assert fresh_db.auto_resolve_slip_outcome(sid) is None              # already resolved
    sid2 = fresh_db.save_slip(slip, "5/2")
    fresh_db.record_outcome(sid2, "WIN", stake=10)
    assert rows("SELECT profit_loss FROM saved_slips WHERE id = ?", sid2)[0]["profit_loss"] == pytest.approx(26.1)
    sid3 = fresh_db.save_slip(slip, "5/2")
    fresh_db.record_outcome(sid3, "LOSS", stake=10)
    assert rows("SELECT profit_loss FROM saved_slips WHERE id = ?", sid3)[0]["profit_loss"] == -10
    assert fresh_db.get_history(user_id=999) == []


def test_propagation_and_unresolved_legs(fresh_db):
    ids = grade_night(fresh_db)
    slip = bet_builder._make_slip([make_vp(name="Jane Doe"), make_vp(name="John Roe", pid=8, market="player_rebounds", line=8.5)], 3.61, 3.6)
    sid = fresh_db.save_slip(slip, "5/2")
    assert len(fresh_db.get_unresolved_legs("2026-04-01")) == 2 and len(fresh_db.get_unresolved_legs()) == 2
    fresh_db.record_graded_prop_result(ids[0], "HIT")
    fresh_db.record_graded_prop_result(ids[2], "MISS")
    assert fresh_db.propagate_results_to_slip_legs("2026-04-01") == 2
    assert fresh_db.auto_resolve_slip_outcome(sid) == "LOSS"


def test_analytics_by_version_and_special_picks(fresh_db):
    ids = grade_night(fresh_db)
    for i, r in zip(ids, ("HIT", "MISS", "HIT", "MISS")):
        fresh_db.record_graded_prop_result(i, r)
    with sqlite3.connect(config.DATABASE_PATH) as c:
        c.execute("UPDATE graded_props SET is_special = 1 WHERE id = ?", (ids[0],))
    a = fresh_db.get_analytics(min_score=60)
    assert a["regular"]["picks"]["total"] == 2 and a["regular"]["picks"]["hits"] == 2
    assert a["by_model_version"][0]["picks"] == 2
    assert a["special_picks"]["total"] == 1 and a["special_picks"]["hit_rate_pct"] == 100.0
    assert a["regular"]["threshold_table"] and a["slips"]["total_slips"] == 0
    assert fresh_db.get_analytics(min_score=99)["regular"]["picks"]["total"] == 0


def test_alt_props_snapshots_and_users(fresh_db):
    alt = make_vp(name="Alt Guy", pid=10, market="player_points_alternate", line=15.5)
    alt.prop.is_alternate = True
    fresh_db.upsert_graded_props([alt], "2026-04-01")
    assert len(fresh_db.get_alt_props("2026-04-01", market="Points", player="Alt", min_score=10, side="over")) == 1
    fresh_db.save_odds_snapshot([("t", "2026-04-01", "e", "Jane Doe", "player_points", "fanduel", 20.5, 1.9, 1.9)])
    fresh_db.save_odds_snapshot([])
    fresh_db.save_refresh_snapshot("2026-04-01", [{"spread": np.float64(-4.5)}], [InjuryReport("A", "BOS", "out")])
    snap = rows("SELECT * FROM refresh_snapshots")[0]
    assert json.loads(snap["injuries_json"])[0]["status"] == "out" and json.loads(snap["games_json"])[0]["spread"] == -4.5
    uid = fresh_db.create_user("jane", "hash", "Jane", is_admin=True)
    assert fresh_db.get_user_by_id(uid)["username"] == "jane"
    assert fresh_db.get_user_by_username("jane")["is_admin"] == 1
    assert fresh_db.get_user_by_username("ghost") is None and fresh_db.get_user_count() == 1


def test_json_helpers():
    assert db._compact({"a": np.int64(2), "b": float("nan"), "c": (1.23456789,), "d": object}) == \
        {"a": 2, "b": None, "c": [1.2346], "d": str(object)}
    js = db._factors_json([FactorResult("Injury Context", 70, 0.1, [], {"teammate_injuries": [
        {"player_name": "A B", "status": "out"}], "x": 1})])
    assert json.loads(js)[0]["data"]["teammate_injuries"] == ["A B:out"]
    names = db._normalise_factor_scores([FactorResult(n, 1, 0, [], {}) for n in
                                         ("Consistency", "vs BOS", "Home Performance", "Injury Context",
                                          "Opponent Defense", "Season Average", "Blowout Risk", "Volume & Usage")])
    assert len(names) == 8
