"""
Live scoring with the hit-probability model.

For one prop and side: build the features (src/analysis/hit_features.py),
get the chance it hits (src/analysis/hit_model.py), compare it with the
market's no-vig chance, and explain it as a "Hit Model" factor. The value
score is that chance on the familiar 0–100 scale (see config.HIT_SCORE_SCALE).
"""
from __future__ import annotations

import pandas as pd

import config
from src.analysis import hit_features, hit_model
from src.analysis.results_checker import _norm_name
from src.api import league_tables
from src.models import FactorResult

# Plain-English names for the factors the model weighs
FEATURE_LABELS = {
    "line_log": "line size", "z_season": "season average vs line", "z_last10": "last 10 games vs line",
    "z_last5": "last 5 games vs line", "z_minadj": "projection from recent minutes",
    "hit_season": "season hit rate at this line", "hit_last10": "hit rate over last 10",
    "nb_logit": "projection model", "min_trend": "minutes trend", "gp_log": "games played",
    "home": "home court", "b2b": "back-to-back", "teammates_out": "teammates out (vs usual)",
    "opp_out": "opponents out (vs usual)", "pace_idx": "game pace", "z_opportunity": "opportunity-based projection",
    "usg": "usage rate", "ts": "shooting efficiency", "drives": "drives per game",
    "pts_per_touch": "points per touch", "fta_pm": "free-throw rate", "opp_def_idx": "opponent defence",
    "opp_pts_allowed_idx": "points the opponent allows", "reb_chances": "rebound chances",
    "reb_contest_pct": "contested rebound share", "reb_pct": "rebound rate",
    "opp_miss_idx": "opponent's missed shots", "opp_reb_allowed_idx": "rebounds the opponent allows",
    "opp_oreb_pct_idx": "opponent's offensive rebounding", "potential_ast": "potential assists",
    "passes_made": "passes per game", "ast_pct": "assist rate", "ast_to_pass_pct": "assists per pass",
    "team_fg_idx": "teammates' shooting", "opp_ast_allowed_idx": "assists the opponent allows",
    "cs_share": "catch-and-shoot share", "fg3a_pg": "3-point attempts", "fg3_pct_shrunk": "3-point %",
    "opp_mix_idx": "3s the opponent allows for his shot type",
    "opp_fg3a_allowed_idx": "3s the opponent allows",
}

def score_from_probability(p: float) -> float:
    """Chance of hitting → value score (50 = coin flip; 70 ≈ 58%; 80 ≈ 62%)."""
    return round(min(100.0, max(0.0, 50.0 + config.HIT_SCORE_SCALE * (p - 0.5))), 1)


def _absences(team: str, date: str, injured: set[str], league_log: pd.DataFrame | None) -> float:
    """Extra regulars' minutes listed out/doubtful tonight vs the team's usual (hit_features.team_absences)."""
    if league_log is None:
        return 0.0
    t = league_log[league_log.TEAM_ABBREVIATION == team]
    return hit_features.team_absences(t, date, tonight_out=injured, norm=_norm_name) if not t.empty else 0.0


def score(
    prop,
    side: str,
    df_raw: pd.DataFrame,
    stat: str,
    market: str,
    team: str,
    opp: str,
    is_home: bool,
    injury_reports: list,
    season: str,
) -> dict | None:
    """Chance this prop/side hits, the market's chance, the edge, and an explaining factor — or None."""
    oo, uo = prop.over_odds_decimal, prop.under_odds_decimal
    if not (oo and uo and oo > 1 and uo > 1):
        return None
    p_mkt_over = (1 / oo) / (1 / oo + 1 / uo)

    log = df_raw.sort_values("GAME_DATE") if not df_raw.empty else df_raw   # oldest first
    rest_days = None
    if not log.empty:
        rest_days = (pd.Timestamp(prop.game.game_date) - pd.Timestamp(log["GAME_DATE"].iloc[-1])).days
    injured = {_norm_name(r.player_name) for r in injury_reports if r.status in ("out", "doubtful")}
    league_log = league_tables.get_league_player_log(season)
    ctx = {
        "player_id": prop.nba_player_id, "team": team, "opp": opp, "is_home": is_home,
        "rest_days": rest_days,
        "teammates_out_min": _absences(team, prop.game.game_date, injured, league_log),
        "opp_out_min": _absences(opp, prop.game.game_date, injured, league_log),
    }
    features = hit_features.build_features(stat, prop.line, p_mkt_over, log,
                                           league_tables.get_snapshot(season) or {}, ctx, allow_partial=True)
    p_full = hit_model.predict_over(market, features) if features else None
    if p_full is None:
        return None

    # The model was trained on players with 12+ games. With fewer, its player
    # stats are much noisier than it knows, so phase them in: price + the
    # structural biases only at ≤3 games → full model at 12.
    games = len(log)
    w = min(1.0, max(0.0, (games - config.HIT_MODEL_MIN_GAMES)
                     / (config.HIT_MODEL_FULL_GAMES - config.HIT_MODEL_MIN_GAMES)))
    p_struct = hit_model.predict_over(market, {"mkt_logit": features["mkt_logit"], "line_log": features["line_log"]})
    p_over = p_struct + w * (p_full - p_struct)

    p_side = p_over if side == "over" else 1 - p_over
    p_mkt = p_mkt_over if side == "over" else 1 - p_mkt_over
    edge = p_side - p_mkt
    info = hit_model.model_info()
    is_special = (edge >= (info.get("special_edge_min") or 0.05)
                  and p_side >= config.SPECIAL_PICK_MIN_PROB
                  and games >= config.HIT_MODEL_FULL_GAMES)   # edge only validated on 12+ game players

    direction = 1 if side == "over" else -1
    contribs = [(c, v * w) for c, v in hit_model.contributions(market, features, top=8)]
    helping = [FEATURE_LABELS.get(c, c) for c, v in contribs if direction * v > 0.02][:3]
    against = [FEATURE_LABELS.get(c, c) for c, v in contribs if direction * v < -0.02][:3]
    evidence = [f"Chance of hitting: {p_side:.0%} — the bookmaker's price implies {p_mkt:.0%} ({edge * 100:+.0f}pp)"]
    if helping:
        evidence.append("Helping: " + ", ".join(helping))
    if against:
        evidence.append("Against: " + ", ".join(against))
    if w < 1.0:
        evidence.append(f"Early season — {games} games played, so player stats count {w:.0%} "
                        f"(full weight from {config.HIT_MODEL_FULL_GAMES} games); special picks start then")
    if is_special:
        evidence.append("★ Special pick — the model's chance beats the market price by a clear margin")

    factor = FactorResult(
        name="Hit Model",
        score=score_from_probability(p_side),
        weight=0.0,   # explanatory: the value score IS this model's output
        evidence=evidence,
        data={"p_side": round(p_side, 4), "p_market": round(p_mkt, 4), "edge": round(edge, 4),
              "is_special": is_special, "stats_weight": round(w, 3), "games": games,
              "contributions": {c: round(v, 4) for c, v in contribs}},
        confidence=1.0,
    )
    return {"p_side": p_side, "p_market": p_mkt, "edge": edge, "is_special": is_special, "factor": factor}
