"""
SQLite persistence layer.

Stores grading runs, saved bet slips, and leg-level outcomes for accuracy
tracking and model calibration over time.

Tables
------
grading_runs      — one record per `refresh` execution
saved_slips       — bet slips explicitly saved by the user
slip_legs         — individual legs of each saved slip, with factor scores
graded_props      — every graded prop: model version, factor details, result, actual stat
model_versions    — each model version seen, with its tunables
odds_snapshots    — every bookmaker's line/odds per refresh (movement, consensus, CLV)
refresh_snapshots — per-refresh spreads + injury report
"""
from __future__ import annotations

import dataclasses
import json
import math
import sqlite3
from datetime import datetime
from typing import Any

import config


# ---------------------------------------------------------------------------
# Factor name normalisation
# ---------------------------------------------------------------------------

def _normalise_factor_scores(factors: list) -> dict[str, float | None]:
    """
    Build a canonical factor-name → score dict from FactorResult objects.

    Some factors use dynamic names (e.g. "vs BOS", "Home Performance")
    so we pattern-match into the stable column keys used by the DB.
    """
    mapping: dict[str, float | None] = {}
    for f in factors:
        low = f.name.lower()
        if low == "consistency":
            mapping["Consistency"] = f.score
        elif low.startswith("vs "):
            mapping["vs Opponent"] = f.score
        elif "performance" in low or low == "home/away":
            mapping["Home/Away"] = f.score
        elif "injury" in low:
            mapping["Injury Context"] = f.score
        elif "opponent" in low and "defense" in low:
            mapping["Opponent Defense"] = f.score
        elif "season" in low:
            mapping["Season Average"] = f.score
        elif "blowout" in low:
            mapping["Blowout Risk"] = f.score
        elif "volume" in low or "usage" in low:
            mapping["Volume & Usage"] = f.score
    return mapping


def _compact(obj: Any) -> Any:
    """JSON-safe copy: floats rounded to 4 dp, NaN/inf → None, numpy/dataclasses unwrapped."""
    if type(obj).__module__ == "numpy":
        obj = obj.tolist()   # numpy scalar → Python scalar, array → list
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, 4)
    if isinstance(obj, dict):
        return {str(k): _compact(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_compact(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def _factors_json(factors: list) -> str:
    """Every factor's score, confidence, weight and raw inputs (evidence text excluded)."""
    def slim(data: dict) -> dict:
        # Injury lists repeat the full report (stored once per refresh in
        # refresh_snapshots) — keep just "name:status" per player here.
        return {
            k: [f"{i.get('player_name')}:{i.get('status')}" for i in v]
               if isinstance(v, list) and v and isinstance(v[0], dict) and "player_name" in v[0]
               else v
            for k, v in (data or {}).items()
        }
    return json.dumps(
        _compact([
            {"name": f.name, "score": f.score, "confidence": f.confidence,
             "weight": f.weight, "data": slim(f.data)}
            for f in factors
        ]),
        separators=(",", ":"),
    )


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # safe concurrent reads
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS grading_runs (
                id             INTEGER PRIMARY KEY,
                run_at         TEXT NOT NULL,
                season         TEXT NOT NULL,
                games_count    INTEGER DEFAULT 0,
                props_total    INTEGER DEFAULT 0,
                props_graded   INTEGER DEFAULT 0,
                props_eligible INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS saved_slips (
                id               INTEGER PRIMARY KEY,
                run_id           INTEGER REFERENCES grading_runs(id),
                saved_at         TEXT NOT NULL,
                target_odds_str  TEXT,
                target_decimal   REAL,
                combined_odds    REAL,
                avg_value_score  REAL,
                has_correlated   INTEGER DEFAULT 0,
                bookmaker_filter TEXT,
                outcome          TEXT,           -- WIN | LOSS | VOID | NULL
                stake            REAL,
                profit_loss      REAL,
                result_at        TEXT
            );

            CREATE TABLE IF NOT EXISTS slip_legs (
                id                   INTEGER PRIMARY KEY,
                slip_id              INTEGER NOT NULL
                                         REFERENCES saved_slips(id) ON DELETE CASCADE,
                player_name          TEXT NOT NULL,
                market               TEXT NOT NULL,
                market_label         TEXT,
                line                 REAL NOT NULL,
                over_odds            REAL NOT NULL,
                bookmaker            TEXT,
                is_paddy_power       INTEGER DEFAULT 0,
                value_score          REAL,
                -- Factor scores at prediction time (for future calibration)
                score_consistency    REAL,
                score_vs_opponent    REAL,
                score_home_away      REAL,
                score_injury         REAL,
                score_team_context   REAL,
                score_season_avg     REAL,
                score_blowout_risk   REAL,
                score_volume_context REAL,
                -- Direction and date — needed for auto result checking
                side                 TEXT,   -- "over" | "under"
                game_date            TEXT,   -- "YYYY-MM-DD"
                -- Actual outcome per leg
                leg_result           TEXT    -- HIT | MISS | NULL
            );

            CREATE INDEX IF NOT EXISTS idx_saved_slips_run_id
                ON saved_slips(run_id);
            CREATE INDEX IF NOT EXISTS idx_slip_legs_slip_id
                ON slip_legs(slip_id);

            -- Persistent prop storage: every graded prop survives cache expiry
            CREATE TABLE IF NOT EXISTS graded_props (
                id                   INTEGER PRIMARY KEY,
                player_name          TEXT NOT NULL,
                nba_player_id        INTEGER,
                market               TEXT NOT NULL,
                market_label         TEXT,
                line                 REAL NOT NULL,
                side                 TEXT NOT NULL,
                game_date            TEXT NOT NULL,
                -- Odds
                over_odds            REAL,
                under_odds           REAL,
                decimal_odds         REAL,
                bookmaker            TEXT,
                is_paddy_power       INTEGER DEFAULT 0,
                is_alternate         INTEGER DEFAULT 0,
                -- Grading output
                value_score          REAL,
                recommendation       TEXT,
                score_consistency    REAL,
                score_vs_opponent    REAL,
                score_home_away      REAL,
                score_injury         REAL,
                score_team_context   REAL,
                score_season_avg     REAL,
                score_blowout_risk   REAL,
                score_volume_context REAL,
                -- Pick tracking
                is_best_side         INTEGER DEFAULT 0,
                -- State
                is_active            INTEGER DEFAULT 1,
                graded_at            TEXT,
                -- Result
                leg_result           TEXT,
                result_at            TEXT,
                -- Display
                matchup              TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_graded_props_unique
                ON graded_props(player_name, market, line, side, game_date);
            CREATE INDEX IF NOT EXISTS idx_graded_props_date
                ON graded_props(game_date);
        """)

        # Users table — for auth & multi-user support
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name  TEXT,
                is_admin      INTEGER DEFAULT 0,
                created_at    TEXT NOT NULL
            )
        """)

        # Migration: add user_id to saved_slips for per-user history
        try:
            conn.execute("ALTER TABLE saved_slips ADD COLUMN user_id INTEGER REFERENCES users(id)")
        except Exception:
            pass

        # Migration: add score_volume_context for databases created before this column existed
        try:
            conn.execute("ALTER TABLE slip_legs ADD COLUMN score_volume_context REAL")
        except Exception:
            pass  # Column already exists — SQLite raises OperationalError in that case

        # Migration: add side and game_date for auto result checking
        try:
            conn.execute("ALTER TABLE slip_legs ADD COLUMN side TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE slip_legs ADD COLUMN game_date TEXT")
        except Exception:
            pass

        # Migration: add nba_player_id for headshot display
        try:
            conn.execute("ALTER TABLE slip_legs ADD COLUMN nba_player_id INTEGER")
        except Exception:
            pass

        # Migration: add score_opponent_defense column (replaces team_context conceptually)
        try:
            conn.execute("ALTER TABLE graded_props ADD COLUMN score_opponent_defense REAL")
        except Exception:
            pass

        # ── Model versioning + richer capture (Oct 2026) ─────────────────
        # Store at grading time what can't be re-fetched later: which model
        # scored the prop and how (factor scores, confidences, inputs), every
        # bookmaker's line per refresh, spreads and the injury report. Actual
        # stat values are filled in by the results checker.
        for ddl in (
            "ALTER TABLE graded_props ADD COLUMN model_version TEXT",
            "ALTER TABLE graded_props ADD COLUMN factors_json TEXT",
            "ALTER TABLE graded_props ADD COLUMN actual_value REAL",
            "ALTER TABLE graded_props ADD COLUMN actual_minutes REAL",
            "ALTER TABLE grading_runs ADD COLUMN model_version TEXT",
            # Hit model (v3): chance of hitting, market's no-vig chance, the edge, special pick
            "ALTER TABLE graded_props ADD COLUMN hit_prob REAL",
            "ALTER TABLE graded_props ADD COLUMN market_prob REAL",
            "ALTER TABLE graded_props ADD COLUMN edge REAL",
            "ALTER TABLE graded_props ADD COLUMN is_special INTEGER DEFAULT 0",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass  # Column already exists
        # Everything graded before versioning existed is the legacy model
        conn.execute(
            "UPDATE graded_props SET model_version = ? WHERE model_version IS NULL",
            (config.LEGACY_MODEL_VERSION,),
        )
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_graded_props_version
                ON graded_props(model_version);

            CREATE TABLE IF NOT EXISTS model_versions (
                version        TEXT PRIMARY KEY,
                base_version   TEXT NOT NULL,
                config_json    TEXT,
                first_seen_at  TEXT NOT NULL,
                last_seen_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id           INTEGER PRIMARY KEY,
                captured_at  TEXT NOT NULL,
                game_date    TEXT,
                event_id     TEXT NOT NULL,
                player_name  TEXT NOT NULL,
                market       TEXT NOT NULL,
                bookmaker    TEXT NOT NULL,
                line         REAL,
                over_odds    REAL,
                under_odds   REAL
            );
            CREATE INDEX IF NOT EXISTS idx_odds_snapshots_lookup
                ON odds_snapshots(game_date, player_name, market);

            CREATE TABLE IF NOT EXISTS refresh_snapshots (
                id             INTEGER PRIMARY KEY,
                captured_at    TEXT NOT NULL,
                game_date      TEXT,
                model_version  TEXT,
                games_json     TEXT,
                injuries_json  TEXT
            );
        """)
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT OR IGNORE INTO model_versions
               (version, base_version, config_json, first_seen_at, last_seen_at)
               VALUES (?, ?, NULL, ?, ?)""",
            (config.LEGACY_MODEL_VERSION, config.LEGACY_MODEL_VERSION, now, now),
        )
        conn.execute(
            """INSERT INTO model_versions
               (version, base_version, config_json, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(version) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
            (
                config.model_version_id(), config.MODEL_VERSION,
                json.dumps(config.model_config_snapshot(), sort_keys=True, default=str),
                now, now,
            ),
        )


# ---------------------------------------------------------------------------
# Grading runs
# ---------------------------------------------------------------------------

def save_grading_run(
    season: str,
    games_count: int,
    props_total: int,
    props_graded: int,
    props_eligible: int,
) -> int:
    """Insert a grading run record and return its row ID."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO grading_runs
               (run_at, season, games_count, props_total, props_graded, props_eligible,
                model_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                season,
                games_count,
                props_total,
                props_graded,
                props_eligible,
                config.model_version_id(),
            ),
        )
        return cur.lastrowid


def get_latest_run_id() -> int | None:
    """Return the most recent grading_run ID, or None if no runs exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM grading_runs ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None


# ---------------------------------------------------------------------------
# Lookup graded props by ID (used by custom slip builder)
# ---------------------------------------------------------------------------

def get_graded_props_by_ids(ids: list[int]) -> list[dict]:
    """Return graded_props rows for specific IDs."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT id, player_name, nba_player_id, market, market_label,
                       line, side, game_date,
                       over_odds, under_odds, decimal_odds,
                       bookmaker, is_paddy_power, is_alternate,
                       value_score, recommendation,
                       matchup, graded_at,
                       score_consistency, score_opponent_defense, score_vs_opponent, score_home_away,
                       score_injury, score_team_context, score_season_avg,
                       score_blowout_risk, score_volume_context
                FROM graded_props
                WHERE id IN ({placeholders})""",
            ids,
        ).fetchall()
        return [dict(r) for r in rows]


def get_graded_prop_id(
    player_name: str, market: str, line: float, side: str, game_date: str,
) -> int | None:
    """Look up the graded_props ID for a specific prop by its unique key."""
    with _connect() as conn:
        row = conn.execute(
            """SELECT id FROM graded_props
               WHERE player_name = ? AND market = ? AND line = ? AND side = ? AND game_date = ?""",
            (player_name, market, line, side, game_date),
        ).fetchone()
        return row["id"] if row else None


def get_all_graded_prop_ids(game_date: str) -> dict[tuple[str, str, float, str], int]:
    """Batch lookup: return {(player_name, market, line, side): id} for a game date.

    Single query replaces 1000+ individual lookups in the /api/props endpoint.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, player_name, market, line, side FROM graded_props
               WHERE game_date = ?""",
            (game_date,),
        ).fetchall()
        return {
            (row["player_name"], row["market"], row["line"], row["side"]): row["id"]
            for row in rows
        }


# ---------------------------------------------------------------------------
# Saving slips
# ---------------------------------------------------------------------------

def save_slip(
    slip: Any,                      # BetSlip — avoid circular import by typing as Any
    target_odds_str: str,
    run_id: int | None = None,
    bookmaker_filter: str | None = None,
    user_id: int | None = None,
) -> int:
    """
    Persist a BetSlip and all its legs to the database.
    Returns the new saved_slip ID.
    """
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO saved_slips
               (run_id, saved_at, target_odds_str, target_decimal,
                combined_odds, avg_value_score, has_correlated, bookmaker_filter, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                datetime.utcnow().isoformat(),
                target_odds_str,
                slip.target_decimal_odds,
                slip.combined_decimal_odds,
                slip.total_value_score,
                int(slip.has_correlated_legs),
                bookmaker_filter,
                user_id,
            ),
        )
        slip_id = cur.lastrowid

        for leg in slip.legs:
            vp = leg.valued_prop
            # Extract factor scores by factor name
            factor_scores = _normalise_factor_scores(vp.factors)
            market_label = config.get_market_label(vp.prop.market)

            conn.execute(
                """INSERT INTO slip_legs
                   (slip_id, player_name, market, market_label, line, over_odds,
                    bookmaker, is_paddy_power, value_score,
                    score_consistency, score_vs_opponent, score_home_away,
                    score_injury, score_team_context, score_season_avg, score_blowout_risk,
                    score_volume_context, side, game_date, nba_player_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slip_id,
                    vp.prop.player_name,
                    vp.prop.market,
                    market_label,
                    vp.prop.line,
                    leg.decimal_odds,
                    vp.prop.bookmaker,
                    int(vp.prop.is_paddy_power),
                    vp.value_score,
                    factor_scores.get("Consistency"),
                    factor_scores.get("vs Opponent"),
                    factor_scores.get("Home/Away"),
                    factor_scores.get("Injury Context"),
                    factor_scores.get("Team Context"),
                    factor_scores.get("Season Average"),
                    factor_scores.get("Blowout Risk"),
                    factor_scores.get("Volume & Usage"),
                    leg.side,
                    vp.prop.game.game_date if vp.prop.game else None,
                    vp.prop.nba_player_id,
                ),
            )

        return slip_id


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_history(limit: int = 20, user_id: int | None = None) -> list[dict]:
    """Return saved slips (newest first) with their legs nested in.
    If user_id is provided, only return slips belonging to that user."""
    with _connect() as conn:
        if user_id is not None:
            slips = conn.execute(
                "SELECT * FROM saved_slips WHERE user_id = ? ORDER BY saved_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            slips = conn.execute(
                "SELECT * FROM saved_slips ORDER BY saved_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        result = []
        for slip in slips:
            legs = conn.execute(
                "SELECT * FROM slip_legs WHERE slip_id = ? ORDER BY id",
                (slip["id"],),
            ).fetchall()
            slip_dict = dict(slip)
            slip_dict["legs"] = [dict(leg) for leg in legs]
            result.append(slip_dict)

        return result


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------

def record_outcome(
    slip_id: int,
    outcome: str,
    stake: float | None = None,
) -> None:
    """
    Record WIN / LOSS / VOID for a saved slip.
    If stake is provided and outcome is WIN, profit_loss is calculated from
    the stored combined_odds.
    """
    profit_loss: float | None = None
    if stake is not None:
        with _connect() as conn:
            row = conn.execute(
                "SELECT combined_odds FROM saved_slips WHERE id = ?", (slip_id,)
            ).fetchone()
            if row and outcome == "WIN":
                profit_loss = round(stake * row["combined_odds"] - stake, 2)
            elif outcome in ("LOSS", "VOID"):
                profit_loss = -stake if outcome == "LOSS" else 0.0

    with _connect() as conn:
        conn.execute(
            """UPDATE saved_slips
               SET outcome=?, stake=?, profit_loss=?, result_at=?
               WHERE id=?""",
            (outcome, stake, profit_loss, datetime.utcnow().isoformat(), slip_id),
        )


def record_leg_result(leg_id: int, result: str) -> None:
    """Record HIT / MISS for an individual leg."""
    with _connect() as conn:
        conn.execute(
            "UPDATE slip_legs SET leg_result=? WHERE id=?",
            (result, leg_id),
        )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _threshold_table(conn, is_alternate: int) -> list[dict]:
    """
    Return hit rate, ROI, and edge at each standard score threshold
    (60+, 65+, 70+, 75+, 80+).  This is always computed across ALL picks
    regardless of whatever min_score filter is active on the main analytics,
    so the table shows the full picture of where the model has edge.
    """
    ROI_EXPR = "CASE WHEN leg_result = 'HIT' THEN decimal_odds - 1 ELSE -1.0 END"
    HAS_ODDS  = "decimal_odds IS NOT NULL AND decimal_odds > 0"
    rows = []
    for threshold in (60, 65, 70, 75, 80):
        r = conn.execute(
            f"""SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits,
                   SUM(CASE WHEN {HAS_ODDS} THEN {ROI_EXPR} END)        AS roi_units,
                   COUNT(CASE WHEN {HAS_ODDS} THEN 1 END)               AS n_odds,
                   AVG(CASE WHEN {HAS_ODDS} THEN 1.0 / decimal_odds END) AS avg_impl
               FROM graded_props
               WHERE leg_result IS NOT NULL AND is_best_side = 1
                 AND is_alternate = {is_alternate}
                 AND value_score >= {threshold}"""
        ).fetchone()
        total    = r["total"] or 0
        hits     = r["hits"]  or 0
        n_odds   = r["n_odds"] or 0
        roi_u    = r["roi_units"]
        avg_impl = r["avg_impl"]
        hit_rate = hits / total if total else 0
        rows.append({
            "min_score":       threshold,
            "total":           total,
            "hits":            hits,
            "hit_rate_pct":    round(hit_rate * 100, 1),
            "roi_pct":         round(roi_u / n_odds * 100, 1) if (n_odds and roi_u is not None) else None,
            "implied_prob_pct":round(avg_impl * 100, 1) if avg_impl else None,
            "edge_pct":        round((hit_rate - avg_impl) * 100, 1) if (avg_impl and total) else None,
        })
    return rows


def _compute_pick_analytics(conn, is_alternate: int, min_score: int = 65) -> dict:
    """
    Run all pick-level analytics queries scoped to regular (0) or alt (1) props,
    filtered to picks with value_score >= min_score.

    Default min_score=65 reflects the minimum score worth recommending to users.
    Including noise-level picks (50-60) would dilute all metrics toward 50%.
    """
    BASE = (
        f"FROM graded_props WHERE leg_result IS NOT NULL"
        f" AND is_best_side = 1 AND is_alternate = {is_alternate}"
        f" AND value_score >= {min_score}"
    )
    # Reusable ROI expression (flat-stake units: HIT earns odds-1, MISS costs 1)
    ROI_EXPR = "CASE WHEN leg_result = 'HIT' THEN decimal_odds - 1 ELSE -1.0 END"
    # Guard: only include rows where odds are recorded and valid
    HAS_ODDS  = "decimal_odds IS NOT NULL AND decimal_odds > 0"

    # ── Summary: picks + ROI / edge metrics ──────────────────────
    sr = conn.execute(
        f"""SELECT
               COUNT(*) AS total_picks,
               SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS total_hits,
               SUM(CASE WHEN {HAS_ODDS} THEN {ROI_EXPR} END) AS roi_units,
               COUNT(CASE WHEN {HAS_ODDS} THEN 1 END)          AS picks_with_odds,
               AVG(CASE WHEN {HAS_ODDS} THEN 1.0 / decimal_odds END) AS avg_implied_prob,
               AVG(CASE WHEN {HAS_ODDS} THEN decimal_odds END)        AS avg_decimal_odds
           {BASE}"""
    ).fetchone()

    total_picks     = sr["total_picks"]     or 0
    total_hits      = sr["total_hits"]      or 0
    total_miss      = total_picks - total_hits
    picks_with_odds = sr["picks_with_odds"] or 0
    roi_units       = sr["roi_units"]           # may be None if no odds recorded
    avg_impl        = sr["avg_implied_prob"]     # may be None
    avg_dec_odds    = sr["avg_decimal_odds"]     # may be None

    hit_rate = total_hits / total_picks if total_picks else 0
    roi_pct  = round(roi_units / picks_with_odds * 100, 1) if (picks_with_odds and roi_units is not None) else None
    impl_pct = round(avg_impl * 100, 1) if avg_impl else None
    edge_pct = round((hit_rate - avg_impl) * 100, 1) if (avg_impl and total_picks) else None

    # ── Value-score calibration (5-point buckets) with ROI/edge ──
    vcal_rows = conn.execute(
        f"""SELECT
               CAST(value_score / 5 AS INTEGER) * 5 AS bucket,
               COUNT(*) AS total,
               SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits,
               SUM(CASE WHEN {HAS_ODDS} THEN {ROI_EXPR} END) AS roi_units,
               COUNT(CASE WHEN {HAS_ODDS} THEN 1 END)          AS n_odds,
               AVG(CASE WHEN {HAS_ODDS} THEN 1.0 / decimal_odds END) AS avg_implied_prob
           {BASE} AND value_score IS NOT NULL
           GROUP BY bucket
           ORDER BY bucket"""
    ).fetchall()

    value_cal: list[dict] = []
    for r in vcal_rows:
        d = dict(r)
        n_odds = d.pop("n_odds", 0) or 0
        ru     = d.pop("roi_units", None)
        ai     = d.pop("avg_implied_prob", None)
        bhr    = d["hits"] / d["total"] if d["total"] else 0
        d["roi_pct"]         = round(ru / n_odds * 100, 1) if (n_odds and ru is not None) else None
        d["avg_implied_prob"]= round(ai, 3) if ai is not None else None
        d["edge_pct"]        = round((bhr - ai) * 100, 1) if (ai is not None and d["total"]) else None
        value_cal.append(d)

    # ── Per-factor calibration (10-point buckets) — no odds needed ─
    factor_cols = [
        ("score_consistency",        "Consistency"),
        ("score_opponent_defense",   "Opponent Defense"),
        ("score_vs_opponent",        "vs Opponent"),
        ("score_home_away",          "Home/Away"),
        ("score_injury",             "Injury"),
        ("score_season_avg",         "Season Avg"),
        ("score_blowout_risk",       "Blowout Risk"),
        ("score_volume_context",     "Volume & Usage"),
    ]
    factor_calibration: dict[str, list[dict]] = {}
    for col, label in factor_cols:
        rows = conn.execute(
            f"""SELECT
                   CAST({col} / 10 AS INTEGER) * 10 AS bucket,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
               {BASE} AND {col} IS NOT NULL
               GROUP BY bucket
               ORDER BY bucket"""
        ).fetchall()
        factor_calibration[label] = [dict(r) for r in rows]

    # ── Hit rate + ROI by market ──────────────────────────────────
    mkt_rows = conn.execute(
        f"""SELECT market_label,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits,
                   SUM(CASE WHEN {HAS_ODDS} THEN {ROI_EXPR} END) AS roi_units,
                   COUNT(CASE WHEN {HAS_ODDS} THEN 1 END)          AS n_odds,
                   AVG(CASE WHEN {HAS_ODDS} THEN 1.0 / decimal_odds END) AS avg_implied_prob
           {BASE}
           GROUP BY market_label
           ORDER BY hits * 1.0 / COUNT(*) DESC"""
    ).fetchall()

    by_market: list[dict] = []
    for r in mkt_rows:
        d = dict(r)
        n_odds = d.pop("n_odds", 0) or 0
        ru     = d.pop("roi_units", None)
        ai     = d.pop("avg_implied_prob", None)
        mhr    = d["hits"] / d["total"] if d["total"] else 0
        d["roi_pct"]  = round(ru / n_odds * 100, 1) if (n_odds and ru is not None) else None
        d["edge_pct"] = round((mhr - ai) * 100, 1) if (ai is not None and d["total"]) else None
        by_market.append(d)

    # ── Hit rate by side ──────────────────────────────────────────
    by_side = conn.execute(
        f"""SELECT side,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE}
           GROUP BY side"""
    ).fetchall()

    # ── Daily trend (hit rate per day) ────────────────────────────
    daily_trend = conn.execute(
        f"""SELECT game_date,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE}
           GROUP BY game_date
           ORDER BY game_date"""
    ).fetchall()

    # ── Daily P&L (for cumulative ROI chart) ─────────────────────
    # Only includes days/picks where we have odds, so cumulative is accurate.
    daily_pnl = conn.execute(
        f"""SELECT game_date,
                   SUM({ROI_EXPR}) AS day_roi_units,
                   COUNT(*) AS picks
           {BASE} AND {HAS_ODDS}
           GROUP BY game_date
           ORDER BY game_date"""
    ).fetchall()

    return {
        "picks": {
            "total":            total_picks,
            "hits":             total_hits,
            "misses":           total_miss,
            "hit_rate":         round(hit_rate, 3),
            # ── New ROI / edge metrics ──
            "roi_pct":          roi_pct,
            "implied_prob_pct": impl_pct,
            "edge_pct":         edge_pct,
            "avg_decimal_odds": round(avg_dec_odds, 2) if avg_dec_odds else None,
            "picks_with_odds":  picks_with_odds,
        },
        "value_calibration": value_cal,
        "factor_calibration": factor_calibration,
        "by_market":   by_market,
        "by_side":     [dict(r) for r in by_side],
        "daily_trend": [dict(r) for r in daily_trend],
        "daily_pnl":   [dict(r) for r in daily_pnl],
    }


def _model_version_table(conn, min_score: int) -> list[dict]:
    """
    Per model version (regular props, best side only): every graded pick, and
    the picks at/above min_score with hit rate, implied probability, edge, ROI.
    Versions cover different dates, so slate/season effects are mixed in —
    compare like-for-like periods where possible.
    """
    ROI_EXPR = "CASE WHEN leg_result = 'HIT' THEN decimal_odds - 1 ELSE -1.0 END"
    HAS_ODDS = "decimal_odds IS NOT NULL AND decimal_odds > 0"
    PICK = f"value_score >= {int(min_score)}"
    rows = conn.execute(
        f"""SELECT COALESCE(model_version, ?) AS version,
                   MIN(game_date) AS first_date,
                   MAX(game_date) AS last_date,
                   COUNT(*) AS graded,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS graded_hits,
                   AVG(value_score) AS avg_score,
                   SUM(CASE WHEN {PICK} THEN 1 ELSE 0 END) AS picks,
                   SUM(CASE WHEN {PICK} AND leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits,
                   SUM(CASE WHEN {PICK} AND {HAS_ODDS} THEN {ROI_EXPR} END) AS roi_units,
                   SUM(CASE WHEN {PICK} AND {HAS_ODDS} THEN 1 ELSE 0 END) AS n_odds,
                   AVG(CASE WHEN {PICK} AND {HAS_ODDS} THEN 1.0 / decimal_odds END) AS avg_impl
            FROM graded_props
            WHERE leg_result IS NOT NULL AND is_best_side = 1 AND is_alternate = 0
            GROUP BY version
            ORDER BY first_date""",
        (config.LEGACY_MODEL_VERSION,),
    ).fetchall()
    out = []
    for r in rows:
        picks, hits = r["picks"] or 0, r["hits"] or 0
        hit_rate = hits / picks if picks else None
        out.append({
            "version":          r["version"],
            "first_date":       r["first_date"],
            "last_date":        r["last_date"],
            "graded":           r["graded"],
            "graded_hit_rate_pct": round(r["graded_hits"] / r["graded"] * 100, 1) if r["graded"] else None,
            "avg_score":        round(r["avg_score"], 1) if r["avg_score"] is not None else None,
            "picks":            picks,
            "hits":             hits,
            "hit_rate_pct":     round(hit_rate * 100, 1) if hit_rate is not None else None,
            "implied_prob_pct": round(r["avg_impl"] * 100, 1) if r["avg_impl"] else None,
            "edge_pct":         round((hit_rate - r["avg_impl"]) * 100, 1)
                                if (hit_rate is not None and r["avg_impl"]) else None,
            "roi_pct":          round(r["roi_units"] / r["n_odds"] * 100, 1)
                                if (r["n_odds"] and r["roi_units"] is not None) else None,
        })
    return out


def _special_picks_summary(conn) -> dict:
    """
    Special picks (model chance beats the market's no-vig price by the trained
    edge — see src/analysis/hit_scoring.py), tracked separately: overall, per
    model version, and per night.
    """
    ROI_EXPR = "CASE WHEN leg_result = 'HIT' THEN decimal_odds - 1 ELSE -1.0 END"
    BASE = ("FROM graded_props WHERE is_special = 1 AND leg_result IS NOT NULL "
            "AND decimal_odds IS NOT NULL AND decimal_odds > 1")

    def summarise(r) -> dict:
        n = r["n"] or 0
        return {
            "total": n,
            "hits": r["hits"] or 0,
            "hit_rate_pct": round((r["hits"] or 0) / n * 100, 1) if n else None,
            "implied_prob_pct": round(r["impl"] * 100, 1) if r["impl"] else None,
            "model_prob_pct": round(r["model"] * 100, 1) if r["model"] else None,
            "roi_pct": round(r["roi"] / n * 100, 1) if n and r["roi"] is not None else None,
        }

    cols = (f"COUNT(*) AS n, SUM(leg_result = 'HIT') AS hits, SUM({ROI_EXPR}) AS roi, "
            "AVG(1.0 / decimal_odds) AS impl, AVG(hit_prob) AS model")
    overall = summarise(conn.execute(f"SELECT {cols} {BASE}").fetchone())
    by_version = [{"version": r["model_version"], **summarise(r)} for r in conn.execute(
        f"SELECT model_version, {cols} {BASE} GROUP BY model_version ORDER BY MIN(game_date)")]
    by_night = [{"game_date": r["game_date"], **summarise(r)} for r in conn.execute(
        f"SELECT game_date, {cols} {BASE} GROUP BY game_date ORDER BY game_date DESC LIMIT 30")]
    return {**overall, "by_version": by_version, "by_night": by_night}


def get_analytics(min_score: int = 65) -> dict:
    """
    Return accuracy analytics split by regular vs alt props.

    min_score filters which picks count toward analytics (default 65 = the
    recommended threshold; picks below this score are not worth evaluating).
    The threshold_table is always computed across all thresholds regardless
    of the active min_score, giving the full picture in one response.

    Top-level keys 'regular' and 'alt' contain full analytics for each type.
    Backward-compat keys (picks, value_calibration, etc.) point to regular data.
    """
    with _connect() as conn:
        regular = _compute_pick_analytics(conn, is_alternate=0, min_score=min_score)
        alt     = _compute_pick_analytics(conn, is_alternate=1, min_score=min_score)

        # ── Threshold comparison table (always at all 5 levels) ───────
        threshold_regular = _threshold_table(conn, is_alternate=0)
        by_model_version  = _model_version_table(conn, min_score)
        special_picks     = _special_picks_summary(conn)
        threshold_alt     = _threshold_table(conn, is_alternate=1)

        # ── Slip-level stats (not split — slips can mix types) ────────
        total_slips = conn.execute(
            "SELECT COUNT(*) FROM saved_slips WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM saved_slips WHERE outcome = 'WIN'"
        ).fetchone()[0]
        pnl_row = conn.execute(
            "SELECT SUM(profit_loss) FROM saved_slips WHERE profit_loss IS NOT NULL"
        ).fetchone()
        total_pnl = pnl_row[0] or 0.0

        return {
            # ── Separated sections (threshold_table included) ─────────
            "regular": {**regular, "threshold_table": threshold_regular},
            "alt":     {**alt,     "threshold_table": threshold_alt},
            # ── Backward-compatible keys (point to regular data) ──────
            "picks":              regular["picks"],
            "value_calibration":  regular["value_calibration"],
            "factor_calibration": regular["factor_calibration"],
            "by_market":          regular["by_market"],
            "by_side":            regular["by_side"],
            "daily_trend":        regular["daily_trend"],
            "daily_pnl":          regular["daily_pnl"],
            # ── Model versions (regular props) ────────────────────────
            "by_model_version": by_model_version,
            "model_version":    config.model_version_id(),
            "special_picks":    special_picks,
            # ── Slip stats (unchanged) ────────────────────────────────
            "slips": {
                "total_slips": total_slips,
                "wins": wins,
                "win_rate": round(wins / total_slips, 3) if total_slips else 0,
                "total_pnl": round(total_pnl, 2),
            },
        }


# ---------------------------------------------------------------------------
# Graded props — persistent storage
# ---------------------------------------------------------------------------

def upsert_graded_props(
    valued_props: list,
    game_date: str,
    mark_stale: bool = True,
) -> list[int]:
    """
    Insert or update graded props for the given game date.

    mark_stale=True  (default): after upserting, marks props for game_date
      that are NOT in this batch as inactive, and recomputes is_best_side.
      Use this when the batch represents the COMPLETE set of props for the date.

    mark_stale=False: upsert only — no stale-marking, no best_side update.
      Use this for intermediate batches during a streaming refresh.  After all
      batches are done, call finalize_graded_props() once with the full set of
      upserted IDs to do the stale-marking and best_side pass in one shot.

    Returns the list of row IDs that were inserted or updated.
    """
    if not valued_props:
        return []

    model_version = config.model_version_id()
    with _connect() as conn:
        upserted_ids: list[int] = []

        for vp in valued_props:
            side = vp.backing_data.get("side", "over")
            decimal_odds = (
                vp.prop.under_odds_decimal if side == "under"
                else vp.prop.over_odds_decimal
            )
            factor_scores = _normalise_factor_scores(vp.factors)
            market_label = config.get_market_label(vp.prop.market)
            game = vp.prop.game
            matchup = f"{game.away_team} @ {game.home_team}" if game else None

            cur = conn.execute(
                """INSERT INTO graded_props
                   (player_name, nba_player_id, market, market_label, line, side,
                    game_date, over_odds, under_odds, decimal_odds,
                    bookmaker, is_paddy_power, is_alternate,
                    value_score, recommendation,
                    score_consistency, score_vs_opponent, score_home_away,
                    score_injury, score_team_context, score_season_avg,
                    score_blowout_risk, score_volume_context,
                    score_opponent_defense,
                    is_active, graded_at, matchup, model_version, factors_json,
                    hit_prob, market_prob, edge, is_special)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)
                   ON CONFLICT(player_name, market, line, side, game_date)
                   DO UPDATE SET
                     nba_player_id  = excluded.nba_player_id,
                     market_label   = excluded.market_label,
                     over_odds      = excluded.over_odds,
                     under_odds     = excluded.under_odds,
                     decimal_odds   = excluded.decimal_odds,
                     bookmaker      = excluded.bookmaker,
                     is_paddy_power = excluded.is_paddy_power,
                     is_alternate   = excluded.is_alternate,
                     value_score    = excluded.value_score,
                     recommendation = excluded.recommendation,
                     score_consistency        = excluded.score_consistency,
                     score_vs_opponent        = excluded.score_vs_opponent,
                     score_home_away          = excluded.score_home_away,
                     score_injury             = excluded.score_injury,
                     score_team_context       = excluded.score_team_context,
                     score_season_avg         = excluded.score_season_avg,
                     score_blowout_risk       = excluded.score_blowout_risk,
                     score_volume_context     = excluded.score_volume_context,
                     score_opponent_defense   = excluded.score_opponent_defense,
                     is_active    = 1,
                     graded_at    = excluded.graded_at,
                     matchup      = excluded.matchup,
                     model_version = excluded.model_version,
                     factors_json  = excluded.factors_json,
                     hit_prob      = excluded.hit_prob,
                     market_prob   = excluded.market_prob,
                     edge          = excluded.edge,
                     is_special    = excluded.is_special
                   RETURNING id""",
                (
                    vp.prop.player_name, vp.prop.nba_player_id,
                    vp.prop.market, market_label, vp.prop.line, side,
                    game_date,
                    vp.prop.over_odds_decimal, vp.prop.under_odds_decimal,
                    decimal_odds, vp.prop.bookmaker,
                    int(vp.prop.is_paddy_power), int(getattr(vp.prop, "is_alternate", False)),
                    vp.value_score, vp.recommendation,
                    factor_scores.get("Consistency"),
                    factor_scores.get("vs Opponent"),
                    factor_scores.get("Home/Away"),
                    factor_scores.get("Injury Context"),
                    None,  # score_team_context — retired, keep column for historical data
                    factor_scores.get("Season Average"),
                    factor_scores.get("Blowout Risk"),
                    factor_scores.get("Volume & Usage"),
                    factor_scores.get("Opponent Defense"),
                    datetime.utcnow().isoformat(),
                    matchup,
                    model_version,
                    _factors_json(vp.factors),
                    vp.backing_data.get("hit_probability"),
                    vp.backing_data.get("market_probability"),
                    vp.backing_data.get("edge"),
                    int(bool(vp.backing_data.get("is_special"))),
                ),
            )
            # RETURNING gives the row id on both paths — cursor.lastrowid is
            # stale when the upsert takes the UPDATE path (an existing prop
            # re-graded), which handed finalize the wrong IDs to stale-mark.
            upserted_ids.append(cur.fetchone()[0])

        if mark_stale:
            # Determine whether this batch is alt or regular so we only
            # mark stale / recompute best_side within the same type.
            batch_is_alt = int(
                getattr(valued_props[0].prop, "is_alternate", False)
            ) if valued_props else 0
            _finalize_graded_props_conn(conn, game_date, upserted_ids, batch_is_alt)

    return upserted_ids


def finalize_graded_props(game_date: str, all_upserted_ids: list[int]) -> None:
    """
    Stale-mark + recompute is_best_side after a multi-batch refresh completes.

    Call this ONCE after all upsert_graded_props(mark_stale=False) batch calls
    are done, passing the combined list of every ID returned by those calls.
    Props for game_date that are NOT in all_upserted_ids are marked inactive
    (they belong to a previous refresh).  is_best_side is then recomputed for
    all active props.
    """
    if not all_upserted_ids:
        return
    with _connect() as conn:
        # Handle regular and alt props independently (same logic, different filter)
        for is_alt in (0, 1):
            _finalize_graded_props_conn(conn, game_date, all_upserted_ids, is_alt)


def _finalize_graded_props_conn(
    conn,
    game_date: str,
    upserted_ids: list[int],
    batch_is_alt: int,
) -> None:
    """
    Inner helper: mark stale and recompute is_best_side using an open connection.
    Operates only on props matching batch_is_alt for game_date.
    """
    if not upserted_ids:
        return

    placeholders = ",".join("?" * len(upserted_ids))

    # Mark stale: props of the SAME type for this date NOT in this ID set → inactive.
    # Only within games this refresh covered — a refresh after some games have
    # tipped off only re-grades the remaining games, and must not deactivate
    # (and drop from analytics) the props of games already under way.
    conn.execute(
        f"""UPDATE graded_props SET is_active = 0
            WHERE game_date = ? AND is_alternate = ?
              AND id NOT IN ({placeholders})
              AND matchup IN (SELECT DISTINCT matchup FROM graded_props
                              WHERE id IN ({placeholders}))""",
        [game_date, batch_is_alt] + upserted_ids + upserted_ids,
    )

    # Compute is_best_side within the SAME type only: for each
    # (player, market, line, date), the side with higher value_score wins.
    conn.execute(
        "UPDATE graded_props SET is_best_side = 0 WHERE game_date = ? AND is_alternate = ?",
        (game_date, batch_is_alt),
    )
    conn.execute(
        """UPDATE graded_props SET is_best_side = 1
           WHERE id IN (
               SELECT id FROM (
                   SELECT id, ROW_NUMBER() OVER (
                       PARTITION BY player_name, market, line, game_date
                       ORDER BY value_score DESC
                   ) rn
                   FROM graded_props
                   WHERE game_date = ? AND is_alternate = ? AND is_active = 1
               ) WHERE rn = 1
           )""",
        (game_date, batch_is_alt),
    )


def repair_deactivated_regular_props() -> int:
    """
    Repair: restore regular props incorrectly marked inactive by the batch-save
    stale-marking bug (each intermediate batch deactivated all previous batches,
    leaving only the final batch as active).

    After reactivating, recomputes is_best_side for every affected game_date
    so picks are correctly flagged.

    Returns the number of rows reactivated.
    """
    with _connect() as conn:
        # Find affected dates before we change anything
        affected = conn.execute(
            "SELECT DISTINCT game_date FROM graded_props WHERE is_alternate = 0 AND is_active = 0"
        ).fetchall()
        affected_dates = [r[0] for r in affected]

        cur = conn.execute(
            "UPDATE graded_props SET is_active = 1 WHERE is_alternate = 0 AND is_active = 0"
        )
        repaired = cur.rowcount

        # Recompute is_best_side for each affected date so picks are correct
        for game_date in affected_dates:
            conn.execute(
                "UPDATE graded_props SET is_best_side = 0 WHERE game_date = ? AND is_alternate = 0",
                (game_date,),
            )
            conn.execute(
                """UPDATE graded_props SET is_best_side = 1
                   WHERE id IN (
                       SELECT id FROM (
                           SELECT id, ROW_NUMBER() OVER (
                               PARTITION BY player_name, market, line, game_date
                               ORDER BY value_score DESC
                           ) rn
                           FROM graded_props
                           WHERE game_date = ? AND is_alternate = 0 AND is_active = 1
                       ) WHERE rn = 1
                   )""",
                (game_date,),
            )

        return repaired


def get_alt_props(
    game_date: str,
    market: str | None = None,
    player: str | None = None,
    min_score: float | None = None,
    side: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Return graded alternate props for a given game date, sorted by value_score DESC."""
    conditions = ["is_alternate = 1", "game_date = ?"]
    params: list = [game_date]

    if market:
        # URLSearchParams encodes "+" as space; restore before matching
        market_norm = market.replace(" ", "+")
        conditions.append("(market = ? OR market_label = ?)")
        params.extend([market_norm, market_norm])
    if player:
        conditions.append("player_name LIKE ?")
        params.append(f"%{player}%")
    if min_score is not None:
        conditions.append("value_score >= ?")
        params.append(min_score)
    if side in ("over", "under"):
        conditions.append("side = ?")
        params.append(side)

    where = " AND ".join(conditions)
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT id, player_name, nba_player_id, market, market_label,
                       line, side, game_date,
                       over_odds, under_odds, decimal_odds,
                       bookmaker, is_paddy_power, is_alternate,
                       value_score, recommendation,
                       is_best_side, is_active, leg_result,
                       matchup, graded_at, result_at,
                       score_consistency, score_opponent_defense, score_vs_opponent, score_home_away,
                       score_injury, score_team_context, score_season_avg,
                       score_blowout_risk, score_volume_context
                FROM graded_props
                WHERE {where}
                ORDER BY value_score DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_unresolved_graded_props(game_date: str) -> list[dict]:
    """Return graded_props rows that haven't been result-checked yet for game_date."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, player_name, market, line, side, game_date
               FROM graded_props
               WHERE leg_result IS NULL AND game_date = ?""",
            (game_date,),
        ).fetchall()
        return [dict(r) for r in rows]


def record_graded_prop_result(
    prop_id: int,
    result: str,
    actual_value: float | None = None,
    actual_minutes: float | None = None,
) -> None:
    """Record HIT / MISS for a graded prop, plus the actual stat and minutes played."""
    with _connect() as conn:
        conn.execute(
            """UPDATE graded_props
               SET leg_result = ?, result_at = ?, actual_value = ?, actual_minutes = ?
               WHERE id = ?""",
            (result, datetime.utcnow().isoformat(), actual_value, actual_minutes, prop_id),
        )


def get_graded_props_missing_actuals(game_date: str) -> list[dict]:
    """Result-checked props for game_date with no actual stat stored (pre-Oct 2026 rows)."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, player_name, market FROM graded_props
               WHERE game_date = ? AND leg_result IS NOT NULL AND actual_value IS NULL""",
            (game_date,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_dates_missing_actuals() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT game_date FROM graded_props
               WHERE leg_result IS NOT NULL AND actual_value IS NULL
               ORDER BY game_date"""
        ).fetchall()
        return [r[0] for r in rows]


def set_graded_prop_actual(prop_id: int, actual_value: float, actual_minutes: float | None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE graded_props SET actual_value = ?, actual_minutes = ? WHERE id = ?",
            (actual_value, actual_minutes, prop_id),
        )


# ---------------------------------------------------------------------------
# Snapshots — market + context data that can't be re-fetched later
# ---------------------------------------------------------------------------

def save_odds_snapshot(rows: list[tuple]) -> None:
    """
    rows: (captured_at, game_date, event_id, player_name, market, bookmaker,
           line, over_odds, under_odds)
    """
    if not rows:
        return
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO odds_snapshots
               (captured_at, game_date, event_id, player_name, market, bookmaker,
                line, over_odds, under_odds)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )


def save_refresh_snapshot(game_date: str | None, games: list[dict], injuries: Any) -> None:
    """Spreads and the injury report as they were when this refresh graded props."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO refresh_snapshots
               (captured_at, game_date, model_version, games_json, injuries_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(), game_date, config.model_version_id(),
                json.dumps(_compact(games), separators=(",", ":")),
                json.dumps(_compact(injuries), separators=(",", ":")),
            ),
        )


def get_model_versions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM model_versions ORDER BY first_seen_at"
        ).fetchall()
        return [dict(r) for r in rows]


def propagate_results_to_slip_legs(game_date: str) -> int:
    """
    Copy leg_result from graded_props to matching slip_legs rows.
    Returns the number of slip_legs rows updated.
    """
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE slip_legs SET leg_result = (
                   SELECT gp.leg_result FROM graded_props gp
                   WHERE gp.player_name = slip_legs.player_name
                     AND gp.market      = slip_legs.market
                     AND gp.line        = slip_legs.line
                     AND gp.side        = slip_legs.side
                     AND gp.game_date   = slip_legs.game_date
                     AND gp.leg_result IS NOT NULL
                   LIMIT 1
               )
               WHERE slip_legs.game_date = ?
                 AND slip_legs.leg_result IS NULL
                 AND slip_legs.side IS NOT NULL""",
            (game_date,),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# Prop results (reads from graded_props)
# ---------------------------------------------------------------------------

def get_prop_results(
    market:     str | None = None,
    player:     str | None = None,
    date_from:  str | None = None,
    date_to:    str | None = None,
    min_score:  float | None = None,
    result:     str | None = None,   # "HIT" | "MISS"
    side:       str | None = None,   # "over" | "under"
    picks_only: bool = False,
    active_only: bool = False,
    graded_only: bool = True,
    alt_filter:  str | None = "regular",  # "regular" | "alt" | "all"
    limit:      int = 500,
) -> list[dict]:
    """
    Return graded_props rows with optional filters.
    Ordered newest first (game_date DESC, value_score DESC).

    alt_filter:
      "regular" (default) — exclude alt lines (is_alternate = 0)
      "alt"               — only alt lines (is_alternate = 1)
      "all" / None        — no filter
    """
    conditions: list[str] = []
    params: list = []

    if graded_only:
        conditions.append("leg_result IS NOT NULL")
    if picks_only:
        conditions.append("is_best_side = 1")
    if active_only:
        conditions.append("is_active = 1")
    if alt_filter == "regular":
        conditions.append("is_alternate = 0")
    elif alt_filter == "alt":
        conditions.append("is_alternate = 1")
    if market:
        # URLSearchParams encodes "+" as space; restore before matching
        market_norm = market.replace(" ", "+")
        conditions.append("(market = ? OR market_label = ?)")
        params.extend([market_norm, market_norm])
    if player:
        conditions.append("player_name LIKE ?")
        params.append(f"%{player}%")
    if date_from:
        conditions.append("game_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("game_date <= ?")
        params.append(date_to)
    if min_score is not None:
        conditions.append("value_score >= ?")
        params.append(min_score)
    if result in ("HIT", "MISS"):
        conditions.append("leg_result = ?")
        params.append(result)
    if side in ("over", "under"):
        conditions.append("side = ?")
        params.append(side)

    where = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT id, player_name, nba_player_id, market, market_label,
                       line, side, game_date,
                       over_odds, under_odds, decimal_odds,
                       bookmaker, is_paddy_power, is_alternate,
                       value_score, recommendation,
                       is_best_side, is_active, leg_result,
                       matchup, graded_at, result_at,
                       score_consistency, score_opponent_defense, score_vs_opponent, score_home_away,
                       score_injury, score_team_context, score_season_avg,
                       score_blowout_risk, score_volume_context,
                       model_version, actual_value, actual_minutes,
                       hit_prob, market_prob, edge, is_special
                FROM graded_props
                WHERE {where}
                ORDER BY game_date DESC, value_score DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Auto result checking helpers
# ---------------------------------------------------------------------------

def get_unresolved_legs(game_date: str | None = None) -> list[dict]:
    """
    Return slip legs that haven't been graded yet and have side + game_date populated.
    Optionally filtered to a specific game_date (ISO date string "YYYY-MM-DD").
    """
    with _connect() as conn:
        if game_date:
            rows = conn.execute(
                """SELECT id, slip_id, player_name, market, line, side, game_date
                   FROM slip_legs
                   WHERE leg_result IS NULL
                     AND side IS NOT NULL
                     AND game_date = ?""",
                (game_date,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, slip_id, player_name, market, line, side, game_date
                   FROM slip_legs
                   WHERE leg_result IS NULL
                     AND side IS NOT NULL
                     AND game_date IS NOT NULL""",
            ).fetchall()
        return [dict(r) for r in rows]


def auto_resolve_slip_outcome(slip_id: int) -> str | None:
    """
    If all legs for slip_id have been graded and the slip has no outcome yet,
    derive WIN (all HIT) or LOSS (any MISS) and record it.
    Returns the outcome string if resolved, else None.
    """
    with _connect() as conn:
        # Check if slip already has an outcome
        slip_row = conn.execute(
            "SELECT outcome FROM saved_slips WHERE id = ?", (slip_id,)
        ).fetchone()
        if not slip_row or slip_row["outcome"] is not None:
            return None

        # Fetch all leg results for this slip
        leg_rows = conn.execute(
            "SELECT leg_result FROM slip_legs WHERE slip_id = ?", (slip_id,)
        ).fetchall()
        if not leg_rows:
            return None

        results = [r["leg_result"] for r in leg_rows]

        # If any leg is still ungraded, can't resolve yet
        if any(r is None for r in results):
            return None

        outcome = "WIN" if all(r == "HIT" for r in results) else "LOSS"

    # record_outcome opens its own connection — call outside the `with` block
    record_outcome(slip_id, outcome)
    return outcome


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def create_user(
    username: str,
    password_hash: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> int:
    """Create a new user and return their ID."""
    from datetime import datetime, timezone

    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO users (username, password_hash, display_name, is_admin, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (username, password_hash, display_name, int(is_admin),
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_user_by_id(user_id: int) -> dict | None:
    """Fetch a user by ID."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    """Fetch a user by username (case-insensitive)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.lower(),)
        ).fetchone()
        return dict(row) if row else None


def get_user_count() -> int:
    """Return total number of registered users."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        return row["cnt"] if row else 0
