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
from concurrent.futures import ThreadPoolExecutor
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
from src.models import BetLeg, BetSlip, FactorResult, NBAGame, PlayerProp, ValuedProp

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
    # One-time repair: restore regular props deactivated by the old
    # stale-marking bug that didn't scope by is_alternate.
    repaired = database.repair_deactivated_regular_props()
    if repaired:
        print(f"[startup] Repaired {repaired} regular props that were incorrectly deactivated.")


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
    "detail": "",  # human-readable detail for terminal + frontend
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

        # Note: get_todays_games() already filters out started/finished games
        # via GAME_STATUS_ID, so no additional filtering needed here.

        def _log(msg: str, detail: str = "") -> None:
            """Print to terminal and update refresh state detail."""
            print(f"[refresh] {msg}")
            with _refresh_lock:
                _refresh_state["detail"] = detail or msg

        _log(f"🏀 Found {len(games)} games tonight")

        # 2. Smart refresh — invalidate props cache so we fetch fresh odds
        cleared = odds_api.invalidate_props_cache()
        if cleared:
            _log(f"🗑️ Cleared {cleared} cached props files — fetching fresh odds")

        # 3. Injuries
        _log("🏥 Fetching injury report…", "Fetching injury report")
        injuries = injury_api.get_injury_report()
        injured_count = sum(len(v) for v in injuries.values()) if isinstance(injuries, dict) else 0
        _log(f"🏥 Injury report: {injured_count} players listed")

        # 4. Events + props
        _log("📡 Fetching odds events…", "Fetching odds events")
        events = odds_api.get_events()
        matched_games = 0
        unmatched_games: list[str] = []
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id
                matched_games += 1
            else:
                unmatched_games.append(f"{game.away_team} @ {game.home_team}")
        if unmatched_games:
            _log(f"⚠️ {len(unmatched_games)} games unmatched: {', '.join(unmatched_games)}")
        _log(f"✅ Matched {matched_games}/{len(games)} games to Odds API")

        all_raw_props: list = []
        for gi, game in enumerate(games):
            matchup = f"{game.away_team} @ {game.home_team}"
            if not game.odds_event_id:
                _log(f"  ⏭️ [{gi+1}/{len(games)}] {matchup} — no odds event, skipping")
                continue
            _log(f"  📥 [{gi+1}/{len(games)}] {matchup} — fetching props…", f"Fetching props: {matchup}")
            raw = odds_api.get_player_props_for_event(game.odds_event_id, force_fresh=True)
            player_id_map: dict[str, int] = {}
            for rp in raw:
                name = rp["player_name"]
                if name not in player_id_map:
                    pid = nba_stats.get_player_id(name)
                    if pid:
                        player_id_map[name] = pid
            props = odds_api.build_player_props(raw, game, player_id_map)
            unique_players = len({p.player_name for p in props})
            _log(f"  ✅ [{gi+1}/{len(games)}] {matchup} — {len(props)} props across {unique_players} players")
            all_raw_props.extend(props)

        # Deduplicate raw props (Odds API can return dupes across event IDs)
        seen_props: set[tuple] = set()
        deduped: list = []
        for p in all_raw_props:
            k = (p.player_name, p.market, p.line, p.bookmaker)
            if k not in seen_props:
                seen_props.add(k)
                deduped.append(p)
        all_raw_props = deduped

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

        # 4a. Pre-warm cache — fetch game logs + current team in parallel
        #     This means grade_prop() will hit cache instantly (no sequential sleeps)
        unique_pids = list({p.nba_player_id for p in all_raw_props if p.nba_player_id})
        total_players = len(unique_pids)
        prefetched = 0

        _log(f"⏳ Pre-warming cache for {total_players} players…", f"Prefetching player data (0/{total_players})")

        # Build a reverse map: player_id → player_name for logging
        _pid_to_name: dict[int, str] = {}
        for p in all_raw_props:
            if p.nba_player_id and p.nba_player_id not in _pid_to_name:
                _pid_to_name[p.nba_player_id] = p.player_name

        def _prefetch(pid: int) -> None:
            nonlocal prefetched
            name = _pid_to_name.get(pid, f"PID {pid}")
            try:
                nba_stats.get_player_game_log(pid, season=season)
                nba_stats.get_player_current_team(pid)
            except Exception:
                print(f"[refresh]   ⚠️ Failed to prefetch {name}")
            prefetched += 1
            if prefetched % 10 == 0 or prefetched == total_players:
                _log(f"  👤 Prefetched {prefetched}/{total_players} players (latest: {name})",
                     f"Prefetching player data ({prefetched}/{total_players})")

        with ThreadPoolExecutor(max_workers=10) as pool:
            pool.map(_prefetch, unique_pids)

        _log(f"✅ Prefetched {total_players} players — grading {len(all_raw_props)} props")
        with _refresh_lock:
            _refresh_state["status"] = "grading"

        # 4b. Grade props (both OVER and UNDER sides) — fast now, all cache hits
        all_valued_props: list[ValuedProp] = []
        _current_player = ""
        for i, prop in enumerate(all_raw_props):
            # Log when we move to a new player
            if prop.player_name != _current_player:
                _current_player = prop.player_name
                player_props = sum(1 for p in all_raw_props if p.player_name == _current_player)
                _log(f"  📊 [{i+1}/{len(all_raw_props)}] Grading {_current_player} ({player_props} markets)…",
                     f"Grading: {_current_player} ({i+1}/{len(all_raw_props)})")

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

        elapsed = (datetime.utcnow() - datetime.fromisoformat(_refresh_state["started_at"])).total_seconds()
        _log(
            f"🏁 Done! {len(all_valued_props)} graded props "
            f"({above_threshold} above threshold) from {len(games)} games "
            f"in {elapsed:.1f}s",
            "done",
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
    side = vp.backing_data.get("side", "over")
    # Look up graded_props ID so frontend can use it for custom slip builder
    prop_id = database.get_graded_prop_id(
        vp.prop.player_name, vp.prop.market, vp.prop.line, side, g.game_date,
    )
    return {
        "prop_id": prop_id,
        "player_name": vp.prop.player_name,
        "player_id": vp.prop.nba_player_id,
        "market": vp.prop.market,
        "market_label": config.get_market_label(vp.prop.market),
        "line": vp.prop.line,
        "side": side,
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
                "market_label": config.get_market_label(leg.valued_prop.prop.market),
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
    """Tonight's NBA games (ET date), deduplicated by game_id."""
    games = nba_stats.get_todays_games()
    seen_ids: set[str] = set()
    result = []
    for g in games:
        if g.game_id not in seen_ids:
            seen_ids.add(g.game_id)
            result.append({
                "game_id": g.game_id,
                "home_team": g.home_team,
                "away_team": g.away_team,
                "matchup": f"{g.away_team} @ {g.home_team}",
                "game_date": g.game_date,
            })
    return result


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
            if vp.prop.bookmaker != bookmaker:
                continue
        if market:
            ml = config.get_market_label(vp.prop.market)
            # URLSearchParams encodes "+" as space; normalise both sides
            if market.replace(" ", "+").lower() != ml.replace(" ", "+").lower():
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
    has_preferred = False
    for vp in vps:
        if vp.prop.bookmaker:
            books.add(vp.prop.bookmaker)
    return sorted(books)


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


# ---------------------------------------------------------------------------
# Custom slip builder
# ---------------------------------------------------------------------------

class CustomSlipRequest(BaseModel):
    leg_ids: list[int]  # graded_props row IDs


@app.post("/api/slips/custom")
def save_custom_slip(req: CustomSlipRequest) -> dict:
    """Save a user-assembled custom slip from graded_props IDs."""
    if not req.leg_ids:
        raise HTTPException(status_code=400, detail="No legs provided.")

    rows = database.get_graded_props_by_ids(req.leg_ids)
    if len(rows) != len(req.leg_ids):
        found_ids = {r["id"] for r in rows}
        missing = [lid for lid in req.leg_ids if lid not in found_ids]
        raise HTTPException(status_code=404, detail=f"Props not found: {missing}")

    legs: list[BetLeg] = []
    for r in rows:
        game = NBAGame(
            game_id="", home_team="", away_team="",
            home_team_id=0, away_team_id=0,
            game_date=r.get("game_date", ""),
            game_time_utc="", odds_event_id="",
        )
        if r.get("matchup"):
            parts = r["matchup"].split(" @ ")
            if len(parts) == 2:
                game.away_team = parts[0].strip()
                game.home_team = parts[1].strip()

        prop = PlayerProp(
            player_name=r["player_name"],
            nba_player_id=r.get("nba_player_id") or 0,
            market=r["market"],
            line=r["line"],
            over_odds_decimal=r.get("over_odds") or r.get("decimal_odds") or 0,
            under_odds_decimal=r.get("under_odds") or 0,
            bookmaker=r.get("bookmaker", "unknown"),
            game=game,
            is_paddy_power=bool(r.get("is_paddy_power")),
            is_alternate=bool(r.get("is_alternate")),
        )
        vp = ValuedProp(
            prop=prop,
            value_score=r["value_score"],
            recommendation=r.get("recommendation", ""),
            factors=_factors_from_db_row(r),
            backing_data={},
        )
        side = r.get("side", "over")
        odds = r.get("decimal_odds") or r.get("over_odds") or 0
        if odds <= 1.0:
            odds = r.get("over_odds") or 1.01
        legs.append(BetLeg(valued_prop=vp, side=side, decimal_odds=float(odds)))

    combined_odds = 1.0
    for leg in legs:
        combined_odds *= leg.decimal_odds
    avg_score = sum(l.valued_prop.value_score for l in legs) / len(legs)
    summary = " | ".join(
        f"{l.valued_prop.prop.player_name} {l.side.upper()} {l.valued_prop.prop.line}"
        for l in legs
    )

    # Check for correlated legs (2+ legs from same game)
    games = [l.valued_prop.prop.game.home_team + l.valued_prop.prop.game.away_team for l in legs]
    has_correlated = len(games) != len(set(g for g in games if g))

    slip = BetSlip(
        legs=legs,
        combined_decimal_odds=round(combined_odds, 3),
        target_decimal_odds=None,
        total_value_score=round(avg_score, 1),
        summary=summary,
        has_correlated_legs=has_correlated,
    )

    run_id = database.get_latest_run_id()
    slip_id = database.save_slip(
        slip=slip,
        target_odds_str="Custom",
        run_id=run_id,
    )
    return {"slip_id": slip_id, "saved": True, "combined_odds": round(combined_odds, 3)}


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
    alt_filter:  Optional[str]   = Query(default="regular"),  # "regular"|"alt"|"all"
    limit:       int             = Query(default=5000),
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
        alt_filter=alt_filter,
        limit=limit,
    )


@app.get("/api/alt-props")
def get_alt_props(
    market:    Optional[str]   = Query(default=None),
    player:    Optional[str]   = Query(default=None),
    min_score: Optional[float] = Query(default=None),
    side:      Optional[str]   = Query(default=None),
    limit:     int             = Query(default=500),
) -> list[dict]:
    """Graded alternate props for today, from the graded_props table."""
    games = nba_stats.get_todays_games()
    if not games:
        return []
    game_date = games[0].game_date
    return database.get_alt_props(
        game_date=game_date,
        market=market,
        player=player,
        min_score=min_score,
        side=side,
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

_alt_refresh_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",   # idle | running | done | no_games | no_props | error
    "props_graded": 0,
    "props_total": 0,
    "error": None,
}
_alt_refresh_lock = threading.Lock()

_ladder_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",   # idle | running | done | no_games | no_props | error
    "props_graded": 0,
    "error": None,
}
_ladder_lock = threading.Lock()


def _select_optimal_alt_lines(
    all_raw_props: list[PlayerProp],
    season: str,
) -> list[PlayerProp]:
    """
    Smart alt-line selection: for each (player, market), pick the ONE line
    that is above the player's statistical floor with odds in the per-leg
    target window (1.15–1.45). Returns ~60-120 props instead of ~3000.
    """
    import pandas as pd

    # Group raw props by (player_id, base_market)
    groups: dict[tuple, list[PlayerProp]] = {}
    for prop in all_raw_props:
        base = config.get_base_market(prop.market)
        key = (prop.nba_player_id, base)
        groups.setdefault(key, []).append(prop)

    selected: list[PlayerProp] = []

    for (pid, base_market), props in groups.items():
        if not pid:
            continue
        market_cfg = config.MARKET_MAP.get(base_market)
        if not market_cfg:
            continue

        # Get cached game log → compute floor (min of last 10 games)
        df = nba_stats.get_player_game_log(pid, season=season)
        if df is None or df.empty or len(df) < config.MIN_GAMES_PLAYED:
            continue

        compute_fn = market_cfg["compute"]
        stat_col = market_cfg["stat_key"] if callable(compute_fn) else compute_fn

        if stat_col not in df.columns:
            # For combo stats (PRA, PR, etc.) the column may need to be computed
            if callable(compute_fn):
                try:
                    df[stat_col] = df.apply(compute_fn, axis=1)
                except Exception:
                    continue
            else:
                continue

        last_10 = df[stat_col].head(10)
        floor = float(last_10.min())
        min_line = floor + config.LADDER_FLOOR_BUFFER

        # Filter props to those with OVER odds in per-leg window and line ≥ floor + buffer
        best_prop: PlayerProp | None = None
        best_odds: float = 0.0

        for prop in props:
            if prop.line < min_line:
                continue
            over_odds = prop.over_odds_decimal
            if config.LADDER_LEG_ODDS_MIN <= over_odds <= config.LADDER_LEG_ODDS_MAX:
                # Pick highest odds (most value) among qualifying lines
                if over_odds > best_odds:
                    best_odds = over_odds
                    best_prop = prop

        if best_prop:
            selected.append(best_prop)

    return selected


def _run_alt_refresh_background(season: str) -> None:
    """
    Alt Lines refresh — fetch + grade alt props (separate from ladder building).
    1. Fetch alt props from Odds API (fast HTTP, no nba_api sleeps)
    2. For each (player, market), pick the ONE optimal line above their floor
    3. Grade only those ~60-120 selected props (game logs already cached)
    4. Persist to DB
    """
    global _alt_refresh_state

    with _alt_refresh_lock:
        _alt_refresh_state.update(
            running=True,
            started_at=datetime.utcnow().isoformat(),
            finished_at=None,
            status="running",
            props_graded=0,
            props_total=0,
            error=None,
        )

    try:
        if not cache.load_scored_props_raw():
            with _alt_refresh_lock:
                _alt_refresh_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="error",
                    error="Run the main refresh first so player data is cached.",
                )
            return

        games = nba_stats.get_todays_games()
        if not games:
            with _alt_refresh_lock:
                _alt_refresh_state.update(running=False, finished_at=datetime.utcnow().isoformat(), status="no_games")
            return

        # Note: get_todays_games() already filters out started/finished games.

        injuries = injury_api.get_injury_report()
        events = odds_api.get_events()
        for game in games:
            event_id = odds_api.match_game_to_event(game, events)
            if event_id:
                game.odds_event_id = event_id

        # 1. Fetch all alt props from Odds API
        all_raw_props: list[PlayerProp] = []
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

        # Deduplicate
        seen_alt: set[tuple] = set()
        deduped_alt: list = []
        for p in all_raw_props:
            k = (p.player_name, p.market, p.line, p.bookmaker)
            if k not in seen_alt:
                seen_alt.add(k)
                deduped_alt.append(p)
        all_raw_props = deduped_alt

        if not all_raw_props:
            with _alt_refresh_lock:
                _alt_refresh_state.update(running=False, finished_at=datetime.utcnow().isoformat(), status="no_props")
            return

        # 2. Smart filter — pick ONE optimal line per (player, market)
        selected = _select_optimal_alt_lines(all_raw_props, season)

        if not selected:
            with _alt_refresh_lock:
                _alt_refresh_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="no_props",
                    error=f"Found {len(all_raw_props)} alt props but none matched floor + odds criteria.",
                )
            return

        with _alt_refresh_lock:
            _alt_refresh_state["props_total"] = len(selected)

        # 3. Grade the selected props
        all_valued_props: list[ValuedProp] = []
        for i, prop in enumerate(selected):
            vp = prop_grader.grade_prop(prop, injuries, season=season, side="over")
            if vp is not None:
                all_valued_props.append(vp)
            with _alt_refresh_lock:
                _alt_refresh_state["props_graded"] = i + 1

        # 4. Persist to DB
        game_date = games[0].game_date if games else None
        if game_date:
            database.upsert_graded_props(all_valued_props, game_date)

        with _alt_refresh_lock:
            _alt_refresh_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="done",
                props_graded=len(all_valued_props),
            )

    except Exception as exc:
        with _alt_refresh_lock:
            _alt_refresh_state.update(
                running=False,
                finished_at=datetime.utcnow().isoformat(),
                status="error",
                error=str(exc),
            )


def _factors_from_db_row(r: dict) -> list[FactorResult]:
    """Reconstruct FactorResult objects from per-factor scores stored in graded_props."""
    factor_map = [
        ("Consistency",       "score_consistency",       config.FACTOR_WEIGHTS["consistency"]),
        ("Opponent Defense",  "score_opponent_defense",   config.FACTOR_WEIGHTS["opponent_defense"]),
        ("vs Opponent",       "score_vs_opponent",        config.FACTOR_WEIGHTS["vs_opponent"]),
        ("Home/Away",         "score_home_away",          config.FACTOR_WEIGHTS["home_away"]),
        ("Injury Context",    "score_injury",             config.FACTOR_WEIGHTS["injury"]),
        ("Season Average",    "score_season_avg",         config.FACTOR_WEIGHTS["season_avg"]),
        ("Blowout Risk",      "score_blowout_risk",       config.FACTOR_WEIGHTS["blowout_risk"]),
        ("Volume & Usage",    "score_volume_context",      config.FACTOR_WEIGHTS["volume_context"]),
    ]
    factors = []
    for name, col, weight in factor_map:
        val = r.get(col)
        if val is not None:
            factors.append(FactorResult(
                name=name, score=float(val), weight=weight,
                evidence=[], data={}, confidence=1.0,
            ))
    return factors


def _run_ladder_build_background(season: str) -> None:
    """
    Build ladder slips from already-graded alt props in the database.
    Does NOT fetch or grade — uses existing data.
    """
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
        # Load graded alt props from DB
        from zoneinfo import ZoneInfo
        game_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        rows = database.get_prop_results(
            date_from=game_date, date_to=game_date,
            alt_filter="alt", graded_only=False,
        )
        if not rows:
            with _ladder_lock:
                _ladder_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="no_props",
                    error="No graded alt props found. Run 'Refresh Alt Lines' first.",
                )
            return

        # Reconstruct ValuedProp objects from DB rows for bet_builder
        all_valued_props: list[ValuedProp] = []
        for r in rows:
            try:
                # Build NBAGame from matchup string (e.g. "BOS @ MIA")
                matchup = r.get("matchup", "") or ""
                game = NBAGame(
                    game_id="", home_team="", away_team="",
                    home_team_id=0, away_team_id=0,
                    game_date=r.get("game_date", ""),
                    game_time_utc="", odds_event_id="",
                )
                if " @ " in matchup:
                    parts = matchup.split(" @ ")
                    game.away_team = parts[0].strip()
                    game.home_team = parts[1].strip()

                prop = PlayerProp(
                    player_name=r["player_name"],
                    nba_player_id=r["nba_player_id"],
                    market=r["market"],
                    line=r["line"],
                    over_odds_decimal=r.get("decimal_odds", 0) or 0,
                    under_odds_decimal=0,
                    bookmaker=r.get("bookmaker", "unknown"),
                    game=game,
                    is_alternate=True,
                )
                vp = ValuedProp(
                    prop=prop,
                    value_score=r["value_score"],
                    recommendation=r.get("recommendation", ""),
                    factors=_factors_from_db_row(r),
                    backing_data={},
                )
                all_valued_props.append(vp)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                continue

        if not all_valued_props:
            with _ladder_lock:
                _ladder_state.update(
                    running=False,
                    finished_at=datetime.utcnow().isoformat(),
                    status="no_props",
                    error="Could not reconstruct alt props from DB.",
                )
            return

        # Build slips
        multi_slips = bet_builder.build_slips(
            all_valued_props,
            target_decimal=config.LADDER_ODDS_TARGET,
            tolerance=config.LADDER_ODDS_TOLERANCE,
            min_score=config.MIN_VALUE_SCORE,
            max_per_player=1,
            force_leg_counts=config.LADDER_LEG_COUNTS,
        )

        multi_slip_dicts = [_slip_to_response(s, "Even Money (~2.0)") for s in multi_slips]
        for d in multi_slip_dicts:
            d["type"] = "multi"

        cache.set("ladder_results", multi_slip_dicts)

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


# --- Alt Lines Refresh endpoints ---

@app.post("/api/alt-refresh")
def trigger_alt_refresh(season: str = config.DEFAULT_SEASON) -> dict:
    """Fetch and grade alt lines from the Odds API."""
    with _alt_refresh_lock:
        if _alt_refresh_state["running"]:
            return {"status": "already_running", "state": dict(_alt_refresh_state)}

    t = threading.Thread(target=_run_alt_refresh_background, args=(season,), daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/api/alt-refresh/status")
def alt_refresh_status() -> dict:
    """Current state of the alt lines refresh."""
    with _alt_refresh_lock:
        return dict(_alt_refresh_state)


# --- Ladder Build endpoints ---

@app.post("/api/ladder")
def trigger_ladder(season: str = config.DEFAULT_SEASON) -> dict:
    """Build ladder slips from already-graded alt props."""
    with _ladder_lock:
        if _ladder_state["running"]:
            return {"status": "already_running", "state": dict(_ladder_state)}

    t = threading.Thread(target=_run_ladder_build_background, args=(season,), daemon=True)
    t.start()
    return {"status": "started"}


@app.get("/api/ladder/status")
def ladder_status() -> dict:
    """Current state of the ladder build."""
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
