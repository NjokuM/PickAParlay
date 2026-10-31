"""
Features for the hit-probability model (src/analysis/hit_model.py).

Shared by the research pipeline (research/hit_model/, which rebuilds them as
of past dates to train) and live grading, so the model sees identical inputs
in both. Pure functions — callers pass in the data:

  log   — the player's games this season BEFORE the graded game, oldest first
          (PlayerGameLog / LeagueGameLog columns: PTS, REB, AST, FG3M, FG3A,
          FGA, FTA, MIN)
  snap  — league tables as of that morning (src/api/league_tables.TABLES;
          live via league_tables.get_snapshot)
  ctx   — player_id, team, opp, is_home, rest_days, teammates_out_min,
          opp_out_min
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.analysis import priors

STAT_COMPONENTS: dict[str, tuple[str, ...]] = {
    "PTS": ("PTS",), "REB": ("REB",), "AST": ("AST",), "FG3M": ("FG3M",),
    "PRA": ("PTS", "REB", "AST"), "PR": ("PTS", "REB"),
    "PA": ("PTS", "AST"), "RA": ("REB", "AST"),
}

MIN_GAMES = 5   # fewer prior games → no model prediction (caller falls back)


def _val(snap: dict, table: str, key, col: str, default: float = float("nan")) -> float:
    try:
        v = snap[table].at[key, col]
        v = float(v.iloc[0]) if isinstance(v, pd.Series) else float(v)
        return default if math.isnan(v) else v
    except (KeyError, TypeError, ValueError):
        return default


def _league_mean(snap: dict, table: str, col: str) -> float:
    try:
        return float(pd.to_numeric(snap[table][col], errors="coerce").mean())
    except KeyError:
        return float("nan")


def _idx(snap: dict, table: str, key, col: str) -> float:
    """Team/player value relative to the league average (1.0 = average; missing → 1.0)."""
    mean = _league_mean(snap, table, col)
    v = _val(snap, table, key, col)
    return 1.0 if (math.isnan(v) or not mean) else v / mean


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def stat_values(log: pd.DataFrame, stat: str) -> pd.Series:
    return sum(pd.to_numeric(log[c], errors="coerce").fillna(0.0) for c in STAT_COMPONENTS[stat])


def team_absences(
    team_log: pd.DataFrame,
    date: str,
    tonight_game_id: str | None = None,
    tonight_out: set[str] | None = None,
    norm=lambda name: name,
    regular_min: float = 15.0,
) -> float:
    """
    Minutes of regulars missing tonight MINUS the team's usual missing minutes
    (average over its last 10 games), in MPG. A player's averages already
    reflect his team's normal absences, so only the difference matters — and
    it keeps early season (few absences) comparable with late season (many).

    team_log: the team's player-game rows this season (LeagueGameLog columns
    PLAYER_ID, PLAYER_NAME, GAME_ID, GAME_DATE as YYYY-MM-DD, MIN). Regulars:
    5+ games, 15+ MPG before `date`, and seen in one of the last 10 games
    (long-term absences are already in the numbers). Tonight's absentees come
    from `tonight_game_id` (training: who actually played) or `tonight_out`
    (live: normalised names listed out/doubtful).
    """
    before = team_log[team_log.GAME_DATE < date]
    if before.empty:
        return 0.0
    games = before.drop_duplicates("GAME_ID").sort_values("GAME_DATE").tail(10)
    recent = before[before.GAME_ID.isin(games.GAME_ID)]
    agg = before.groupby("PLAYER_ID").agg(gp=("GAME_ID", "size"), mpg=("MIN", "mean"),
                                          first=("GAME_DATE", "min"), name=("PLAYER_NAME", "first"))
    regs = agg[(agg.gp >= 5) & (agg.mpg >= regular_min) & agg.index.isin(recent.PLAYER_ID)]
    if regs.empty:
        return 0.0
    if tonight_game_id is not None:
        played = set(team_log.loc[team_log.GAME_ID == tonight_game_id, "PLAYER_ID"])
        tonight = float(regs.loc[~regs.index.isin(played), "mpg"].sum())
    else:
        out = tonight_out or set()
        tonight = float(sum(m for n, m in zip(regs.name, regs.mpg) if norm(n) in out))
    played_by_game = recent.groupby("GAME_ID").PLAYER_ID.apply(set)
    usual = [float(regs[(regs["first"] <= gdate) & ~regs.index.isin(played_by_game.get(gid, set()))].mpg.sum())
             for gid, gdate in zip(games.GAME_ID, games.GAME_DATE)]
    return tonight - (sum(usual) / len(usual) if usual else 0.0)


def build_features(
    stat: str,
    line: float,
    p_mkt_over: float,
    log: pd.DataFrame,
    snap: dict,
    ctx: dict,
    allow_partial: bool = False,
) -> dict[str, float] | None:
    """
    Feature dict for P(stat > line), or None if there's too little data. With
    allow_partial, a player with fewer than MIN_GAMES games gets market-only
    features (the model treats every missing feature as average).
    """
    if stat not in STAT_COMPONENTS:
        return None
    if log is None or len(log) < MIN_GAMES:
        return {"mkt_logit": _logit(p_mkt_over), "line_log": math.log(line + 0.5)} if allow_partial else None
    s = stat_values(log, stat)
    mins = pd.to_numeric(log["MIN"], errors="coerce").fillna(0.0)
    n = len(s)
    season, last10, last5 = float(s.mean()), float(s.tail(10).mean()), float(s.tail(5).mean())
    sd = max(float(s.std(ddof=1)), 0.5 + 0.15 * max(line, 0.0))
    mpg, mpg5 = float(mins.mean()), float(mins.tail(5).mean())
    rate = float(s.sum()) / max(float(mins.sum()), 1.0)
    pid, team, opp = ctx.get("player_id"), ctx.get("team"), ctx.get("opp")

    f: dict[str, float] = {
        # Market — the single best predictor; the model learns how far to trust it
        "mkt_logit": _logit(p_mkt_over),
        "line_log": math.log(line + 0.5),
        # Form vs the line, in units of the player's own game-to-game spread
        "z_season": (season - line) / sd,
        "z_last10": (last10 - line) / sd,
        "z_last5": (last5 - line) / sd,
        "z_minadj": (rate * mpg5 - line) / sd,
        "hit_season": float((s > line).mean()),
        "hit_last10": float((s.tail(10) > line).mean()),
        "nb_logit": _logit(priors.prob_hit(season, stat, line, "over")),
        "min_trend": (mpg5 - mpg) / max(mpg, 1.0),
        "gp_log": math.log(n),
        # Context
        "home": 1.0 if ctx.get("is_home") else 0.0,
        "b2b": 1.0 if (ctx.get("rest_days") or 9) <= 1 else 0.0,
        # extra minutes of regulars missing vs the team's usual (team_absences), per 10 MPG
        "teammates_out": float(ctx.get("teammates_out_min") or 0.0) / 10.0,
        "opp_out": float(ctx.get("opp_out_min") or 0.0) / 10.0,
        "pace_idx": (_idx(snap, "tadv", team, "PACE") + _idx(snap, "tadv", opp, "PACE")) / 2,
    }
    comps = set(STAT_COMPONENTS[stat])

    # Opportunity-based projection: chances are steadier than conversions, so
    # project from opportunities × a conversion rate shrunk toward league average.
    proj_parts = []
    if "PTS" in comps:
        f["usg"] = _val(snap, "padv", pid, "USG_PCT", 0.2)
        f["ts"] = _val(snap, "padv", pid, "TS_PCT", 0.57)
        f["drives"] = _val(snap, "drive", pid, "DRIVES", 0.0)
        f["pts_per_touch"] = _val(snap, "poss", pid, "PTS_PER_TOUCH", 0.25)
        f["fta_pm"] = float(pd.to_numeric(log["FTA"], errors="coerce").fillna(0).sum()) / max(float(mins.sum()), 1.0)
        f["opp_def_idx"] = _idx(snap, "tadv", opp, "DEF_RATING")
        f["opp_pts_allowed_idx"] = _idx(snap, "topp", opp, "OPP_PTS")
        proj_parts.append(float(stat_values(log, "PTS").mean()))
    if "REB" in comps:
        chances = _val(snap, "reb", pid, "REB_CHANCES")
        conv = _val(snap, "reb", pid, "REB_CHANCE_PCT")
        lg_conv = _league_mean(snap, "reb", "REB_CHANCE_PCT")
        f["reb_chances"] = 0.0 if math.isnan(chances) else chances
        f["reb_contest_pct"] = _val(snap, "reb", pid, "REB_CONTEST_PCT", 0.3)
        f["reb_pct"] = _val(snap, "padv", pid, "REB_PCT", 0.1)
        f["opp_miss_idx"] = (
            (_val(snap, "tbase", opp, "FGA", 88) - _val(snap, "tbase", opp, "FGM", 41))
            / max(_league_mean(snap, "tbase", "FGA") - _league_mean(snap, "tbase", "FGM"), 1.0)
        )
        f["opp_reb_allowed_idx"] = _idx(snap, "topp", opp, "OPP_REB")
        f["opp_oreb_pct_idx"] = _idx(snap, "tadv", opp, "OREB_PCT")
        reb_avg = float(stat_values(log, "REB").mean())
        proj_parts.append(reb_avg if math.isnan(chances) or math.isnan(conv) or math.isnan(lg_conv)
                          else chances * (0.5 * conv + 0.5 * lg_conv))
    if "AST" in comps:
        pot = _val(snap, "pass", pid, "POTENTIAL_AST")
        ast_avg = float(stat_values(log, "AST").mean())
        lg_conv = (_league_mean(snap, "pass", "AST") / _league_mean(snap, "pass", "POTENTIAL_AST"))
        conv = (ast_avg / pot) if (pot and not math.isnan(pot)) else float("nan")
        f["potential_ast"] = 0.0 if math.isnan(pot) else pot
        f["passes_made"] = _val(snap, "pass", pid, "PASSES_MADE", 0.0)
        f["ast_pct"] = _val(snap, "padv", pid, "AST_PCT", 0.1)
        f["ast_to_pass_pct"] = _val(snap, "pass", pid, "AST_TO_PASS_PCT", 0.1)
        f["team_fg_idx"] = _idx(snap, "tbase", team, "FG_PCT")
        f["opp_ast_allowed_idx"] = _idx(snap, "topp", opp, "OPP_AST")
        proj_parts.append(ast_avg if math.isnan(conv) or math.isnan(lg_conv)
                          else pot * (0.5 * min(conv, 1.0) + 0.5 * lg_conv))
    if "FG3M" in comps:
        cs_a = _val(snap, "cs", pid, "CATCH_SHOOT_FG3A", 0.0)
        pu_a = _val(snap, "pu", pid, "PULL_UP_FG3A", 0.0)
        cs_share = cs_a / (cs_a + pu_a) if (cs_a + pu_a) > 0 else 0.6
        fg3a = float(pd.to_numeric(log["FG3A"], errors="coerce").fillna(0).sum())
        fg3m = float(pd.to_numeric(log["FG3M"], errors="coerce").fillna(0).sum())
        pct = (fg3m + 0.36 * 50) / (fg3a + 50)          # shrunk toward league ~36%
        f["cs_share"] = cs_share
        f["fg3a_pg"] = fg3a / n
        f["fg3_pct_shrunk"] = pct
        f["opp_mix_idx"] = cs_share * _idx(snap, "ocs", opp, "FG3A") + (1 - cs_share) * _idx(snap, "opu", opp, "FG3A")
        f["opp_fg3a_allowed_idx"] = _idx(snap, "topp", opp, "OPP_FG3A")
        proj_parts.append(f["fg3a_pg"] * pct)
    f["z_opportunity"] = (sum(proj_parts) - line) / sd if proj_parts else f["z_season"]

    return {k: (0.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)) for k, v in f.items()}
