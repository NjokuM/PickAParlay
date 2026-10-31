"""
Training data for the hit-probability model: one row per graded prop line,
with features rebuilt as of the morning of the game (src/analysis/hit_features.py)
and whether the OVER hit.

    python research/hit_model/build_dataset.py <season> <graded_props.json> \
        <player_game_log.pkl> <snapshots.pkl> <out.pkl> [last_date]

graded_props.json — rows from GET /api/prop-results?graded_only=true&alt_filter=regular
player_game_log.pkl — LeagueGameLog(player_or_team_abbreviation="P") for the season
snapshots.pkl — research/hit_model/snapshots.py output for the props' game dates
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.analysis.hit_features import build_features, role_absorption, team_absences  # noqa: E402

MARKET_STAT = {
    "player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST",
    "player_threes": "FG3M", "player_points_rebounds_assists": "PRA",
    "player_points_rebounds": "PR", "player_points_assists": "PA",
    "player_rebounds_assists": "RA",
}


def load_lines(path: str, last_date: str | None) -> pd.DataFrame:
    """One row per (player, date, market, line) with the over outcome and no-vig market price."""
    lines: dict[tuple, dict] = {}
    for r in json.load(open(path)):
        if r["market"] not in MARKET_STAT or r.get("is_alternate") or not r.get("leg_result"):
            continue
        if last_date and r["game_date"] > last_date:
            continue
        oo, uo = r.get("over_odds") or 0, r.get("under_odds") or 0
        if oo <= 1 or uo <= 1:
            continue
        over_hit = (r["leg_result"] == "HIT") if r["side"] == "over" else (r["leg_result"] == "MISS")
        key = (r["nba_player_id"], r["game_date"], r["market"], r["line"])
        lines[key] = dict(player_id=r["nba_player_id"], player=r["player_name"], date=r["game_date"],
                          market=r["market"], stat=MARKET_STAT[r["market"]], line=float(r["line"]),
                          over_odds=oo, under_odds=uo, over_hit=int(over_hit),
                          old_score_over=r["value_score"] if r["side"] == "over" else lines.get(key, {}).get("old_score_over"),
                          old_score_under=r["value_score"] if r["side"] == "under" else lines.get(key, {}).get("old_score_under"))
    df = pd.DataFrame(lines.values())
    po, pu = 1 / df.over_odds, 1 / df.under_odds
    df["p_mkt_over"] = po / (po + pu)
    return df


def main(season, props_path, log_path, snap_path, out_path, last_date=None):
    lines = load_lines(props_path, last_date)
    gl = pd.read_pickle(log_path)
    gl["GAME_DATE"] = pd.to_datetime(gl.GAME_DATE).dt.strftime("%Y-%m-%d")
    gl = gl[pd.to_numeric(gl.MIN, errors="coerce").fillna(0) > 0].sort_values("GAME_DATE")
    snaps = pickle.load(open(snap_path, "rb"))

    by_player = {pid: g.reset_index(drop=True) for pid, g in gl.groupby("PLAYER_ID")}
    played_in = defaultdict(set)                          # game_id → player_ids who played
    for gid, pid in zip(gl.GAME_ID, gl.PLAYER_ID):
        played_in[gid].add(pid)
    team_games = {t: g for t, g in gl.groupby("TEAM_ABBREVIATION")}

    memo: dict[tuple, float] = {}

    def regulars_out(team: str, game_id: str, date: str) -> float:
        """Extra regulars' minutes missing vs the team's usual (src/analysis/hit_features.team_absences)."""
        if (team, game_id) not in memo:
            t = team_games.get(team)
            memo[(team, game_id)] = 0.0 if t is None else team_absences(t, date, tonight_game_id=game_id)
        return memo[(team, game_id)]

    role_memo: dict[tuple, dict] = {}

    def role_for(team: str, game_id: str, date: str, pid: int) -> dict:
        if (team, game_id) not in role_memo:
            t = team_games.get(team)
            role_memo[(team, game_id)] = {} if t is None else role_absorption(t, date, tonight_game_id=game_id)
        return role_memo[(team, game_id)].get(pid, {})

    rows, skipped = [], defaultdict(int)
    for r in lines.itertuples():
        p = by_player.get(r.player_id)
        if p is None:
            skipped["no game log"] += 1; continue
        today = p[p.GAME_DATE == r.date]
        before = p[p.GAME_DATE < r.date]
        if today.empty:
            skipped["did not play"] += 1; continue
        if r.date not in snaps:
            skipped["no snapshot"] += 1; continue
        g = today.iloc[0]
        home = " vs. " in g.MATCHUP
        opp = g.MATCHUP.split(" vs. " if home else " @ ")[-1].strip()
        rest = (pd.Timestamp(r.date) - pd.Timestamp(before.GAME_DATE.iloc[-1])).days if len(before) else 9
        ctx = dict(player_id=r.player_id, team=g.TEAM_ABBREVIATION, opp=opp, is_home=home, rest_days=rest,
                   teammates_out_min=regulars_out(g.TEAM_ABBREVIATION, g.GAME_ID, r.date),
                   opp_out_min=regulars_out(opp, g.GAME_ID, r.date),
                   role_absorption=role_for(g.TEAM_ABBREVIATION, g.GAME_ID, r.date, r.player_id))
        f = build_features(r.stat, r.line, r.p_mkt_over, before, snaps[r.date], ctx)
        if f is None:
            skipped["< 5 prior games"] += 1; continue
        rows.append({**r._asdict(), "team": ctx["team"], "opp": opp, **f})
    out = pd.DataFrame(rows).drop(columns=["Index"])
    out.to_pickle(out_path)
    print(f"{len(out)} rows from {len(lines)} lines | skipped {dict(skipped)}")
    print(out.groupby("market").size().to_string())


if __name__ == "__main__":
    main(*sys.argv[1:])
