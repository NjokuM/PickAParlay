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
                -- Actual outcome per leg
                leg_result           TEXT    -- HIT | MISS | NULL
            );

            CREATE INDEX IF NOT EXISTS idx_saved_slips_run_id
                ON saved_slips(run_id);
            CREATE INDEX IF NOT EXISTS idx_slip_legs_slip_id
                ON slip_legs(slip_id);
        """)

        # Migration: add score_volume_context for databases created before this column existed
        try:
            conn.execute("ALTER TABLE slip_legs ADD COLUMN score_volume_context REAL")
        except Exception:
            pass  # Column already exists — SQLite raises OperationalError in that case


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
# Saving slips
# ---------------------------------------------------------------------------

def save_slip(
    slip: Any,                      # BetSlip — avoid circular import by typing as Any
    target_odds_str: str,
    run_id: int | None = None,
    bookmaker_filter: str | None = None,
) -> int:
    """
    Persist a BetSlip and all its legs to the database.
    Returns the new saved_slip ID.
    """
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO saved_slips
               (run_id, saved_at, target_odds_str, target_decimal,
                combined_odds, avg_value_score, has_correlated, bookmaker_filter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                datetime.utcnow().isoformat(),
                target_odds_str,
                slip.target_decimal_odds,
                slip.combined_decimal_odds,
                slip.total_value_score,
                int(slip.has_correlated_legs),
                bookmaker_filter,
            ),
        )
        slip_id = cur.lastrowid

        for leg in slip.legs:
            vp = leg.valued_prop
            # Extract factor scores by factor name
            factor_scores: dict[str, float | None] = {f.name: f.score for f in vp.factors}
            market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)

            conn.execute(
                """INSERT INTO slip_legs
                   (slip_id, player_name, market, market_label, line, over_odds,
                    bookmaker, is_paddy_power, value_score,
                    score_consistency, score_vs_opponent, score_home_away,
                    score_injury, score_team_context, score_season_avg, score_blowout_risk,
                    score_volume_context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )

        return slip_id


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_history(limit: int = 20) -> list[dict]:
    """Return saved slips (newest first) with their legs nested in."""
    with _connect() as conn:
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

def get_analytics() -> dict:
    """
    Return aggregate accuracy statistics for the history page / CLI.
    Only includes slips/legs where outcomes have been recorded.
    """
    with _connect() as conn:
        # Overall slip win rate
        total_slips = conn.execute(
            "SELECT COUNT(*) FROM saved_slips WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM saved_slips WHERE outcome = 'WIN'"
        ).fetchone()[0]

        # Leg hit rate by market
        market_stats = conn.execute(
            """SELECT market_label,
                      COUNT(*) AS total,
                      SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
               FROM slip_legs
               WHERE leg_result IS NOT NULL
               GROUP BY market_label
               ORDER BY hits * 1.0 / COUNT(*) DESC"""
        ).fetchall()

        # P&L
        pnl_row = conn.execute(
            "SELECT SUM(profit_loss) FROM saved_slips WHERE profit_loss IS NOT NULL"
        ).fetchone()
        total_pnl = pnl_row[0] or 0.0

        # Factor score calibration buckets (consistency score vs actual hit rate)
        calibration = conn.execute(
            """SELECT
                   CAST(score_consistency / 10 AS INTEGER) * 10 AS bucket,
                   COUNT(*) AS total,
                   SUM(CASE WHEN leg_result = 'HIT' THEN 1 ELSE 0 END) AS hits
               FROM slip_legs
               WHERE leg_result IS NOT NULL AND score_consistency IS NOT NULL
               GROUP BY bucket
               ORDER BY bucket"""
        ).fetchall()

        return {
            "overall": {
                "total_slips": total_slips,
                "wins": wins,
                "win_rate": round(wins / total_slips, 3) if total_slips else 0,
                "total_pnl": round(total_pnl, 2),
            },
            "by_market": [dict(r) for r in market_stats],
            "calibration": [dict(r) for r in calibration],
        }
