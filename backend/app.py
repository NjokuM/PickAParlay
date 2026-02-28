"""
PickAParlay — FastAPI Backend

Wraps the existing src/ pipeline with REST endpoints so the Next.js
frontend can talk to the same grading engine without duplicating logic.

Start with:
    uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import dataclasses
import os
import sys
import threading
from datetime import datetime
from typing import Optional

# Ensure the project root is on sys.path so all src/ imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import src.cache as cache
import src.database as database
from src.api import injury_api, nba_stats, odds_api
from src.analysis import bet_builder, prop_grader, results_checker
from src.models import BetSlip, FactorResult, NBAGame, PlayerProp, ValuedProp

app = FastAPI(title="PickAParlay API", version="1.0.0")

# Allow the Next.js dev server and any local origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    database.init_db()


# ---------------------------------------------------------------------------
# Background refresh state
# ---------------------------------------------------------------------------

_refresh_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",   # idle | running | done | no_games | no_props | error
    "props_graded": 0,
    "props_total": 0,
    "run_id": None,
    "error": None,
}
_refresh_lock = threading.Lock()


def _run_refresh_background(season: str) -> None:
    global _refresh_state

    with _refresh_lock:
        _refresh_state.update(
            running=True,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            status="running",
            props_graded=0,
            props_total=0,
            run_id=None,
            error=None,
        )

    try:
        # 1. Tonight's games
        games = nba_stats.get_todays_games()
        if not games:
            with _refresh_lock:
                _refresh_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="no_games",
                )
            return

        # 2. Injuries
        injuries = injury_api.get_injury_report()

        # 3. Events + props
        events = odds_api.get_events()
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id

        all_raw_props: list = []
        for game in games:
            if game.odds_event_id:
                raw = odds_api.get_player_props_for_event(game.odds_event_id)
                player_id_map: dict[str, int] = {}
                for rp in raw:
                    name = rp["player_name"]
                    if name not in player_id_map:
                        pid = nba_stats.get_player_id(name)
                        if pid:
                            player_id_map[name] = pid
                props = odds_api.build_player_props(raw, game, player_id_map)
                all_raw_props.extend(props)

        with _refresh_lock:
            _refresh_state["props_total"] = len(all_raw_props)

        if not all_raw_props:
            with _refresh_lock:
                _refresh_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="no_props",
                )
            return

        # 4. Grade props (both OVER and UNDER sides)
        all_valued_props: list[ValuedProp] = []
        for i, prop in enumerate(all_raw_props):
            vp_over = prop_grader.grade_prop(prop, injuries, season=season, side="over")
            if vp_over is not None:
                all_valued_props.append(vp_over)
            # Grade UNDER if a valid under price exists
            if prop.under_odds_decimal and prop.under_odds_decimal > 1.0:
                vp_under = prop_grader.grade_prop(prop, injuries, season=season, side="under")
                if vp_under is not None:
                    all_valued_props.append(vp_under)
            with _refresh_lock:
                _refresh_state["props_graded"] = i + 1

        # 5. Cache scored props
        prop_dicts = [dataclasses.asdict(vp) for vp in all_valued_props]
        cache.save_scored_props(prop_dicts)

        # 5b. Persist all graded props to the database (upsert)
        game_date = games[0].game_date if games else None
        if game_date:
            database.upsert_graded_props(all_valued_props, game_date)

        above_threshold = sum(
            1 for vp in all_valued_props if vp.value_score >= config.MIN_VALUE_SCORE
        )

        run_id = database.save_grading_run(
            season=season,
            games_count=len(games),
            props_total=len(all_raw_props),
            props_graded=len(all_valued_props),
            props_eligible=above_threshold,
        )

        with _refresh_lock:
            _refresh_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="done",
                props_graded=len(all_valued_props),
                run_id=run_id,
            )

    except Exception as exc:
        with _refresh_lock:
            _refresh_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="error",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Reconstruction helpers
# ---------------------------------------------------------------------------

def _vp_from_dict(d: dict) -> ValuedProp:
    game_d = d["prop"]["game"]
    game = NBAGame(**game_d)

    prop_d = dict(d["prop"])
    prop_d["game"] = game
    prop = PlayerProp(**prop_d)

    factors = [FactorResult(**f) for f in d["factors"]]

    return ValuedProp(
        prop=prop,
        value_score=d["value_score"],
        factors=factors,
        recommendation=d["recommendation"],
        backing_data=d.get("backing_data", {}),
        suspicious_line=d.get("suspicious_line", False),
        suspicious_reason=d.get("suspicious_reason", ""),
    )


def _vp_to_response(vp: ValuedProp) -> dict:
    g = vp.prop.game
    return {
        "player_name": vp.prop.player_name,
        "player_id": vp.prop.nba_player_id,
        "market": vp.prop.market,
        "market_label": config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market),
        "line": vp.prop.line,
        "side": vp.backing_data.get("side", "over"),
        "over_odds": vp.prop.over_odds_decimal,
        "bookmaker": vp.prop.bookmaker,
        "is_paddy_power": vp.prop.is_paddy_power,
        "value_score": round(vp.value_score, 1),
        "recommendation": vp.recommendation,
        "game": f"{g.away_team} @ {g.home_team}",
        "game_date": g.game_date,
        "suspicious_line": vp.suspicious_line,
        "suspicious_reason": vp.suspicious_reason,
        "factors": [
            {
                "name": f.name,
                "score": round(f.score, 1),
                "weight": f.weight,
                "evidence": f.evidence,
                "confidence": f.confidence,
            }
            for f in vp.factors
        ],
        "backing_data": vp.backing_data,
    }


def _slip_to_response(slip: BetSlip, odds_str: str) -> dict:
    return {
        "combined_odds": round(slip.combined_decimal_odds, 3),
        "target_decimal": slip.target_decimal_odds,
        "target_odds_str": odds_str,
        "avg_value_score": round(slip.total_value_score, 1),
        "has_correlated_legs": slip.has_correlated_legs,
        "summary": slip.summary,
        "legs": [
            {
                "player_name": leg.valued_prop.prop.player_name,
                "player_id": leg.valued_prop.prop.nba_player_id,
                "market": leg.valued_prop.prop.market,
                "market_label": config.MARKET_MAP.get(
                    leg.valued_prop.prop.market, {}
                ).get("label", leg.valued_prop.prop.market),
                "line": leg.valued_prop.prop.line,
                "side": leg.side,
                "over_odds": leg.decimal_odds,
                "bookmaker": leg.valued_prop.prop.bookmaker,
                "is_paddy_power": leg.valued_prop.prop.is_paddy_power,
                "value_score": round(leg.valued_prop.value_score, 1),
                "recommendation": leg.valued_prop.recommendation,
                "game": (
                    f"{leg.valued_prop.prop.game.away_team} @ "
                    f"{leg.valued_prop.prop.game.home_team}"
                ),
                "factors": [
                    {
                        "name": f.name,
                        "score": round(f.score, 1),
                        "weight": f.weight,
                    }
                    for f in leg.valued_prop.factors
                ],
            }
            for leg in slip.legs
        ],
    }


def _parse_odds(odds_str: str) -> float:
    odds_str = odds_str.strip()
    if "/" in odds_str:
        a, b = odds_str.split("/")
        return round(float(a) / float(b) + 1, 4)
    if odds_str.startswith("+"):
        return round(float(odds_str[1:]) / 100 + 1, 4)
    if odds_str.startswith("-"):
        return round(100 / abs(float(odds_str)) + 1, 4)
    val = float(odds_str)
    if val <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {val}")
    return round(val, 4)


def _load_valued_props() -> list[ValuedProp]:
    raw_dicts = cache.load_scored_props_raw()
    if not raw_dicts:
        return []
    result = []
    for d in raw_dicts:
        try:
            result.append(_vp_from_dict(d))
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tonight")
def get_tonight() -> list[dict]:
    """Tonight's NBA games (ET date)."""
    games = nba_stats.get_todays_games()
    return [
        {
            "game_id": g.game_id,
            "home_team": g.home_team,
            "away_team": g.away_team,
            "matchup": f"{g.away_team} @ {g.home_team}",
            "game_date": g.game_date,
        }
        for g in games
    ]


@app.get("/api/props")
def get_props(
    min_score: float = Query(default=0.0),
    game: Optional[str] = Query(default=None),
    player: Optional[str] = Query(default=None),
    bookmaker: Optional[str] = Query(default=None),
    market: Optional[str] = Query(default=None),
    side: Optional[str] = Query(default=None),
) -> list[dict]:
    """All scored props for today, optionally filtered."""
    vps = _load_valued_props()
    result = []
    for vp in vps:
        if vp.value_score < min_score:
            continue
        g_str = f"{vp.prop.game.away_team} @ {vp.prop.game.home_team}"
        if game and game.upper() not in g_str.upper():
            continue
        if player and player.lower() not in vp.prop.player_name.lower():
            continue
        if bookmaker:
            if bookmaker.lower() == "paddypower":
                if not vp.prop.is_paddy_power:
                    continue
            elif vp.prop.bookmaker != bookmaker:
                continue
        if market:
            ml = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
            if market.lower() not in ml.lower():
                continue
        if side and vp.backing_data.get("side", "over") != side.lower():
            continue
        result.append(_vp_to_response(vp))

    result.sort(key=lambda x: x["value_score"], reverse=True)
    return result


@app.get("/api/bookmakers")
def get_bookmakers() -> list[str]:
    """Distinct bookmakers present in today's cached props."""
    vps = _load_valued_props()
    books: set[str] = set()
    has_pp = False
    for vp in vps:
        if vp.prop.bookmaker:
            books.add(vp.prop.bookmaker)
        if vp.prop.is_paddy_power:
            has_pp = True
    result = sorted(books)
    if has_pp and "paddypower" not in result:
        result = ["paddypower"] + result
    return result


@app.post("/api/refresh")
def trigger_refresh(season: str = config.DEFAULT_SEASON) -> dict:
    """Kick off the full fetch + grade pipeline in a background thread."""
    with _refresh_lock:
        if _refresh_state["running"]:
            return {"status": "already_running", "state": dict(_refresh_state)}

    t = threading.Thread(
        target=_run_refresh_background, args=(season,), daemon=True
    )
    t.start()
    return {"status": "started"}


@app.get("/api/refresh/status")
def refresh_status() -> dict:
    """Current state of the background refresh."""
    with _refresh_lock:
        return dict(_refresh_state)


@app.get("/api/slips")
def get_slips(
    odds: Optional[str] = Query(default=None),
    legs: Optional[int] = Query(default=None),
    min_score: Optional[float] = Query(default=None),
    bookmaker: Optional[str] = Query(default=None),
) -> list[dict]:
    """Build bet slips from cached props — instant, no API calls.
    When odds is omitted (or empty), returns highest-confidence combos regardless of odds.
    """
    if not cache.load_scored_props_raw():
        raise HTTPException(
            status_code=404,
            detail="No cached props. POST /api/refresh first.",
        )

    target_decimal: Optional[float] = None
    if odds:
        try:
            target_decimal = _parse_odds(odds)
        except (ValueError, ZeroDivisionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    vps = _load_valued_props()
    threshold = min_score if min_score is not None else config.MIN_VALUE_SCORE
    slips = bet_builder.build_slips(
        vps,
        target_decimal=target_decimal,
        n_legs=legs,
        min_score=threshold,
        bookmaker=bookmaker,
    )
    return [_slip_to_response(s, odds or "Best Value") for s in slips]


class SaveSlipRequest(BaseModel):
    odds: Optional[str] = None
    slip_index: int = 0
    bookmaker: Optional[str] = None
    legs: Optional[int] = None
    min_score: Optional[float] = None


@app.post("/api/slips/save")
def save_slip_endpoint(req: SaveSlipRequest) -> dict:
    """Re-build slips and save the chosen one to the database."""
    if not cache.load_scored_props_raw():
        raise HTTPException(status_code=404, detail="No cached props.")

    target_decimal: Optional[float] = None
    if req.odds:
        try:
            target_decimal = _parse_odds(req.odds)
        except (ValueError, ZeroDivisionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    vps = _load_valued_props()
    threshold = req.min_score if req.min_score is not None else config.MIN_VALUE_SCORE
    slips = bet_builder.build_slips(
        vps,
        target_decimal=target_decimal,
        n_legs=req.legs,
        min_score=threshold,
        bookmaker=req.bookmaker,
    )

    if req.slip_index >= len(slips):
        raise HTTPException(
            status_code=404,
            detail=f"Slip index {req.slip_index} out of range (only {len(slips)} slips).",
        )

    slip = slips[req.slip_index]
    run_id = database.get_latest_run_id()
    slip_id = database.save_slip(
        slip=slip,
        target_odds_str=req.odds or "Best Value",
        run_id=run_id,
        bookmaker_filter=req.bookmaker,
    )
    return {"slip_id": slip_id, "saved": True}


@app.get("/api/history")
def get_history(limit: int = Query(default=20)) -> list[dict]:
    """Saved slips with nested legs, newest first."""
    return database.get_history(limit=limit)


class OutcomeRequest(BaseModel):
    outcome: str                                    # WIN | LOSS | VOID
    stake: Optional[float] = None
    leg_results: Optional[dict[str, str]] = None   # {str(leg_id): "HIT"|"MISS"}


@app.patch("/api/history/{slip_id}/outcome")
def record_outcome_endpoint(slip_id: int, req: OutcomeRequest) -> dict:
    """Record WIN / LOSS / VOID for a slip (and optionally HIT/MISS per leg)."""
    if req.outcome not in ("WIN", "LOSS", "VOID"):
        raise HTTPException(
            status_code=400, detail="outcome must be WIN, LOSS, or VOID"
        )

    database.record_outcome(slip_id, req.outcome, req.stake)

    if req.leg_results:
        for leg_id_str, result in req.leg_results.items():
            if result in ("HIT", "MISS"):
                database.record_leg_result(int(leg_id_str), result)

    return {"updated": True, "slip_id": slip_id}


@app.get("/api/prop-results")
def get_prop_results_endpoint(
    market:      Optional[str]   = Query(default=None),
    player:      Optional[str]   = Query(default=None),
    date_from:   Optional[str]   = Query(default=None),
    date_to:     Optional[str]   = Query(default=None),
    min_score:   Optional[float] = Query(default=None),
    result:      Optional[str]   = Query(default=None),
    side:        Optional[str]   = Query(default=None),
    picks_only:  bool            = Query(default=False),
    active_only: bool            = Query(default=False),
    graded_only: bool            = Query(default=True),
    limit:       int             = Query(default=500),
) -> list[dict]:
    """Individual graded props from graded_props table with optional filters."""
    return database.get_prop_results(
        market=market,
        player=player,
        date_from=date_from,
        date_to=date_to,
        min_score=min_score,
        result=result,
        side=side,
        picks_only=picks_only,
        active_only=active_only,
        graded_only=graded_only,
        limit=limit,
    )


@app.get("/api/analytics")
def get_analytics() -> dict:
    """Factor accuracy stats and P&L from all recorded outcomes."""
    return database.get_analytics()


@app.get("/api/credits")
def get_credits() -> dict:
    """Odds API credit usage for this month."""
    return {
        "used": cache.get_credits_used(),
        "remaining": cache.get_credits_remaining(),
        "total": 500,
    }


# ---------------------------------------------------------------------------
# Ladder Challenge — background state + pipeline
# ---------------------------------------------------------------------------

_ladder_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",   # idle | running | done | no_games | no_props | error
    "props_graded": 0,
    "error": None,
}
_ladder_lock = threading.Lock()


def _run_ladder_background(season: str) -> None:
    """Fetch alternate props for all tonight's games, grade them, build ~2.0 slips."""
    global _ladder_state

    with _ladder_lock:
        _ladder_state.update(
            running=True,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            status="running",
            props_graded=0,
            error=None,
        )

    try:
        games = nba_stats.get_todays_games()
        if not games:
            with _ladder_lock:
                _ladder_state.update(running=False, finished_at=datetime.utcnow().isoformat(), status="no_games")
            return

        injuries = injury_api.get_injury_report()
        events = odds_api.get_events()
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id

        all_raw_props: list = []
        for game in games:
            if not game.odds_event_id:
                continue
            raw = odds_api.get_alternate_props_for_event(game.odds_event_id)
            player_id_map: dict[str, int] = {}
            for rp in raw:
                name = rp["player_name"]
                if name not in player_id_map:
                    pid = nba_stats.get_player_id(name)
                    if pid:
                        player_id_map[name] = pid
            props = odds_api.build_player_props(raw, game, player_id_map)
            all_raw_props.extend(props)

        if not all_raw_props:
            with _ladder_lock:
                _ladder_state.update(running=False, finished_at=datetime.utcnow().isoformat(), status="no_props")
            return

        # Grade OVER and UNDER for each alternate prop
        all_valued_props: list[ValuedProp] = []
        for i, prop in enumerate(all_raw_props):
            vp_over = prop_grader.grade_prop(prop, injuries, season=season, side="over")
            if vp_over is not None:
                all_valued_props.append(vp_over)
            if prop.under_odds_decimal and prop.under_odds_decimal > 1.0:
                vp_under = prop_grader.grade_prop(prop, injuries, season=season, side="under")
                if vp_under is not None:
                    all_valued_props.append(vp_under)
            with _ladder_lock:
                _ladder_state["props_graded"] = i + 1

        # Persist alternate graded props to DB
        game_date = games[0].game_date if games else None
        if game_date:
            database.upsert_graded_props(all_valued_props, game_date)

        # Build multi-leg slips targeting ~2.0 (1.95–2.30 window)
        multi_slips = bet_builder.build_slips(
            all_valued_props,
            target_decimal=config.LADDER_ODDS_TARGET,
            tolerance=config.LADDER_ODDS_TOLERANCE,
            min_score=config.MIN_VALUE_SCORE,
        )

        # Build single-leg picks: props whose relevant-side odds are in the ladder window
        single_leg_slips: list[dict] = []
        seen_singles: set[tuple] = set()
        for vp in sorted(all_valued_props, key=lambda v: v.value_score, reverse=True):
            if vp.value_score < config.MIN_VALUE_SCORE:
                continue
            side = vp.backing_data.get("side", "over")
            odds_val = (
                vp.prop.under_odds_decimal if side == "under" else vp.prop.over_odds_decimal
            )
            if not (config.LADDER_ODDS_MIN <= odds_val <= config.LADDER_ODDS_MAX):
                continue
            key = (vp.prop.player_name, vp.prop.market, vp.prop.line, side)
            if key in seen_singles:
                continue
            seen_singles.add(key)
            g = vp.prop.game
            market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
            single_leg_slips.append({
                "type": "single",
                "combined_odds": round(odds_val, 3),
                "target_decimal": config.LADDER_ODDS_TARGET,
                "target_odds_str": "Even Money (~2.0)",
                "avg_value_score": round(vp.value_score, 1),
                "has_correlated_legs": False,
                "summary": (
                    f"{vp.prop.player_name} {side.upper()} {vp.prop.line} {market_label} "
                    f"@{odds_val:.2f}"
                ),
                "legs": [
                    {
                        "player_name": vp.prop.player_name,
                        "player_id": vp.prop.nba_player_id,
                        "market": vp.prop.market,
                        "market_label": market_label,
                        "line": vp.prop.line,
                        "side": side,
                        "over_odds": odds_val,
                        "bookmaker": vp.prop.bookmaker,
                        "is_paddy_power": vp.prop.is_paddy_power,
                        "value_score": round(vp.value_score, 1),
                        "recommendation": vp.recommendation,
                        "game": f"{g.away_team} @ {g.home_team}",
                        "factors": [
                            {"name": f.name, "score": round(f.score, 1), "weight": f.weight}
                            for f in vp.factors
                        ],
                    }
                ],
            })
            if len(single_leg_slips) >= 5:
                break

        multi_slip_dicts = [_slip_to_response(s, "Even Money (~2.0)") for s in multi_slips]
        # Mark multi-leg slips for frontend differentiation
        for d in multi_slip_dicts:
            d["type"] = "multi"

        all_results = single_leg_slips + multi_slip_dicts
        cache.set("ladder_results", all_results)

        with _ladder_lock:
            _ladder_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="done",
                props_graded=len(all_valued_props),
            )

    except Exception as exc:
        with _ladder_lock:
            _ladder_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="error",
                error=str(exc),
            )


@app.post("/api/ladder")
def trigger_ladder(season: str = config.DEFAULT_SEASON) -> dict:
    """Kick off the alternate-props fetch + grade + build in a background thread."""
    with _ladder_lock:
        if _ladder_state["running"]:
            return {"status": "already_running", "state": dict(_ladder_state)}

    t = threading.Thread(target=_run_ladder_background, args=(season,), daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/api/ladder/status")
def ladder_status() -> dict:
    """Current state of the ladder background job."""
    with _ladder_lock:
        return dict(_ladder_state)


@app.get("/api/ladder/results")
def ladder_results() -> list[dict]:
    """Return cached ladder slips (single + multi leg, near even money)."""
    data = cache.get("ladder_results", config.CACHE_TTL["props"])
    if data is None:
        return []
    return data


# ---------------------------------------------------------------------------
# Results auto-check — background state + pipeline
# ---------------------------------------------------------------------------

_results_state: dict = {
    "status": "idle",       # idle | running | done | error
    "game_date": None,
    "started_at": None,
    "finished_at": None,
    "checked": 0,
    "hit": 0,
    "miss": 0,
    "no_data": 0,
    "slips_resolved": 0,
    "error": None,
}
_results_lock = threading.Lock()


def _run_results_background(game_date: str) -> None:
    """Fetch box scores for game_date and grade all unresolved saved prop legs."""
    global _results_state

    with _results_lock:
        _results_state.update(
            status="running",
            game_date=game_date,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            checked=0,
            hit=0,
            miss=0,
            no_data=0,
            slips_resolved=0,
            error=None,
        )

    try:
        summary = results_checker.check_results_for_date(game_date)
        with _results_lock:
            _results_state.update(
                status="done",
                finished_at=datetime.utcnow().isoformat(),
                checked=summary["checked"],
                hit=summary["hit"],
                miss=summary["miss"],
                no_data=summary["no_data"],
                slips_resolved=summary["slips_resolved"],
            )
    except Exception as exc:
        with _results_lock:
            _results_state.update(
                status="error",
                finished_at=datetime.utcnow().isoformat(),
                error=str(exc),
            )


@app.post("/api/results/check")
def trigger_results_check(game_date: str = Query(..., description="YYYY-MM-DD")) -> dict:
    """Kick off background result checking for all saved prop legs on game_date."""
    with _results_lock:
        if _results_state["status"] == "running":
            return {"status": "already_running", "state": dict(_results_state)}

    t = threading.Thread(
        target=_run_results_background, args=(game_date,), daemon=True
    )
    t.start()
    return {"status": "started", "game_date": game_date}


@app.get("/api/results/status")
def results_check_status() -> dict:
    """Current state of the background results-check job."""
    with _results_lock:
        return dict(_results_state)


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
