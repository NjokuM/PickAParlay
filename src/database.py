"""
SQLite persistence layer.

Stores grading runs, saved bet slips, and leg-level outcomes for accuracy
tracking and model calibration over time.

Tables
------
grading_runs  — one record per `refresh` execution
saved_slips   — bet slips explicitly saved by the user
slip_legs     — individual legs of each saved slip, with factor scores
"""
from __future__ import annotations

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
               (run_at, season, games_count, props_total, props_graded, props_eligible)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                season,
                games_count,
                props_total,
                props_graded,
                props_eligible,
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

def _compute_pick_analytics(conn, is_alternate: int) -> dict:
    """Run all pick-level analytics queries scoped to regular (0) or alt (1) props."""
    BASE = (
        f"FROM graded_props WHERE leg_result IS NOT NULL"
        f" AND is_best_side = 1 AND is_alternate = {is_alternate}"
    )

    total_picks = conn.execute(f"SELECT COUNT(*) {BASE}").fetchone()[0]
    total_hits  = conn.execute(
        f"SELECT COUNT(*) {BASE} AND leg_result = 'HIT'"
    ).fetchone()[0]
    total_miss  = total_picks - total_hits

    # ── Value-score calibration (5-point buckets) ─────────────────
    value_cal = conn.execute(
        f"""SELECT
               CAST(value_score / 5 AS INTEGER) * 5 AS bucket,
               COUNT(*) AS total,
               SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE} AND value_score IS NOT NULL
           GROUP BY bucket
           ORDER BY bucket"""
    ).fetchall()

    # ── Per-factor calibration (10-point buckets) ─────────────────
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

    # ── Hit rate by market ────────────────────────────────────────
    by_market = conn.execute(
        f"""SELECT market_label,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE}
           GROUP BY market_label
           ORDER BY hits * 1.0 / COUNT(*) DESC"""
    ).fetchall()

    # ── Hit rate by side ──────────────────────────────────────────
    by_side = conn.execute(
        f"""SELECT side,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE}
           GROUP BY side"""
    ).fetchall()

    # ── Daily trend ───────────────────────────────────────────────
    daily_trend = conn.execute(
        f"""SELECT game_date,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
           {BASE}
           GROUP BY game_date
           ORDER BY game_date"""
    ).fetchall()

    return {
        "picks": {
            "total": total_picks,
            "hits": total_hits,
            "misses": total_miss,
            "hit_rate": round(total_hits / total_picks, 3) if total_picks else 0,
        },
        "value_calibration": [dict(r) for r in value_cal],
        "factor_calibration": factor_calibration,
        "by_market": [dict(r) for r in by_market],
        "by_side": [dict(r) for r in by_side],
        "daily_trend": [dict(r) for r in daily_trend],
    }


def get_analytics() -> dict:
    """
    Return accuracy analytics split by regular vs alt props.
    Top-level keys 'regular' and 'alt' contain full analytics for each type.
    Backward-compat keys (picks, value_calibration, etc.) point to regular data.
    """
    with _connect() as conn:
        regular = _compute_pick_analytics(conn, is_alternate=0)
        alt     = _compute_pick_analytics(conn, is_alternate=1)

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
            # ── New separated sections ────────────────────────────────
            "regular": regular,
            "alt":     alt,
            # ── Backward-compatible keys (point to regular data) ──────
            "picks":              regular["picks"],
            "value_calibration":  regular["value_calibration"],
            "factor_calibration": regular["factor_calibration"],
            "by_market":          regular["by_market"],
            "by_side":            regular["by_side"],
            "daily_trend":        regular["daily_trend"],
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

def upsert_graded_props(valued_props: list, game_date: str) -> int:
    """
    Insert or update ALL graded props for the given game date.
    After upserting, marks stale props as inactive and computes is_best_side.
    Returns count of rows upserted.
    """
    if not valued_props:
        return 0

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
                    is_active, graded_at, matchup)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
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
                     matchup      = excluded.matchup""",
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
                ),
            )
            # lastrowid returns the inserted id, or the existing id on conflict
            upserted_ids.append(cur.lastrowid)

        # Determine whether this batch is alt or regular so we only
        # mark stale / recompute best_side within the same type.
        batch_is_alt = int(
            getattr(valued_props[0].prop, "is_alternate", False)
        ) if valued_props else 0

        # Mark stale: props of the SAME type for this date NOT in batch → inactive
        if upserted_ids:
            placeholders = ",".join("?" * len(upserted_ids))
            conn.execute(
                f"""UPDATE graded_props SET is_active = 0
                    WHERE game_date = ? AND is_alternate = ?
                      AND id NOT IN ({placeholders})""",
                [game_date, batch_is_alt] + upserted_ids,
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
                       WHERE game_date = ? AND is_alternate = ?
                   ) WHERE rn = 1
               )""",
            (game_date, batch_is_alt),
        )

    return len(upserted_ids)


def repair_deactivated_regular_props() -> int:
    """One-time repair: restore regular props that were incorrectly marked
    inactive by the old stale-marking bug (which didn't scope by is_alternate)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE graded_props SET is_active = 1 WHERE is_alternate = 0 AND is_active = 0"
        )
        return cur.rowcount


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


def record_graded_prop_result(prop_id: int, result: str) -> None:
    """Record HIT / MISS for a graded prop."""
    with _connect() as conn:
        conn.execute(
            "UPDATE graded_props SET leg_result = ?, result_at = ? WHERE id = ?",
            (result, datetime.utcnow().isoformat(), prop_id),
        )


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
                       score_blowout_risk, score_volume_context
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
