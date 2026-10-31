"""
How much of a missing teammate's production does each player absorb?

For every player-game in a season, compare the player's actual stat with his
season average (as of that morning) and test candidate "injury" signals:
  A  minutes of regulars missing (what the model uses today)
  B  share-based: each absentee's per-game stat × the player's share of that
     stat among teammates who are playing
  C  role-weighted: like B, but weighted by how similar the player's role is
     to the absentee's (per-36 profile: rebounds, assists, 3PA, 2PA) — a
     backup SG's minutes go to guards, not the starting center
All signals use only games before the one being predicted.

    python research/hit_model/injury_redistribution.py <player_game_log.pkl>
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np
import pandas as pd

STATS = ["PTS", "REB", "AST", "FG3A", "FG3M", "MIN"]
REGULAR_MPG = 10.0


def profile(rows: pd.DataFrame) -> np.ndarray:
    """Per-36 role vector: rebounds, assists, 3PA, 2PA (unit length)."""
    m = max(rows.MIN.sum(), 1.0)
    v = np.array([rows.REB.sum(), rows.AST.sum(), rows.FG3A.sum(), (rows.FGA - rows.FG3A).sum()]) / m * 36
    n = np.linalg.norm(v)
    return v / n if n else v


def main(log_path: str) -> pd.DataFrame:
    gl = pd.read_pickle(log_path)
    gl["GAME_DATE"] = pd.to_datetime(gl.GAME_DATE).dt.strftime("%Y-%m-%d")
    gl["MIN"] = pd.to_numeric(gl.MIN, errors="coerce").fillna(0)
    gl = gl[gl.MIN > 0].sort_values("GAME_DATE")
    out = []
    for team, t in gl.groupby("TEAM_ABBREVIATION"):
        games = t.drop_duplicates("GAME_ID")[["GAME_ID", "GAME_DATE"]].values
        for i, (gid, d) in enumerate(games):
            if i < 10:
                continue
            before = t[t.GAME_DATE < d]
            recent_ids = set(before[before.GAME_ID.isin(games[max(0, i - 10):i, 0])].PLAYER_ID)
            agg = before.groupby("PLAYER_ID").agg(gp=("GAME_ID", "size"), **{s: (s, "mean") for s in STATS})
            regs = agg[(agg.gp >= 5) & (agg.MIN >= REGULAR_MPG) & agg.index.isin(recent_ids)]
            tonight = t[t.GAME_ID == gid]
            playing = set(tonight.PLAYER_ID)
            absent = regs[~regs.index.isin(playing)]
            active = regs[regs.index.isin(playing)]
            if active.empty:
                continue
            profiles = {pid: profile(before[before.PLAYER_ID == pid]) for pid in regs.index}
            # similarity of each active player to each absentee, normalised over active players
            sim = {(p, a): max(0.0, float(profiles[p] @ profiles[a])) for p in active.index for a in absent.index}
            for p, row in tonight.set_index("PLAYER_ID").iterrows():
                if p not in active.index or active.at[p, "gp"] < 10:
                    continue
                rec = {"team": team, "date": d, "player_id": p, "gp": active.at[p, "gp"],
                       "A_minutes_out": float(absent.MIN.sum()),
                       **{f"base_{s}": float(active.at[p, s]) for s in STATS}}
                for s in STATS:
                    rec[f"delta_{s}"] = float(row[s]) - float(active.at[p, s])
                    share = active.at[p, s] / max(active[s].sum(), 1e-6)
                    rec[f"B_{s}"] = float((absent[s] * share).sum())
                    c = 0.0
                    for a in absent.index:
                        tot = sum(sim[(q, a)] * active.at[q, s] for q in active.index)
                        if tot > 0:
                            c += absent.at[a, s] * sim[(p, a)] * active.at[p, s] / tot
                    rec[f"C_{s}"] = c
                out.append(rec)
    df = pd.DataFrame(out)
    print(f"{len(df)} player-games, {df.team.nunique()} teams; games with a regular out: {(df.A_minutes_out > 0).mean():.0%}\n")
    print("Correlation with (actual − season average) — higher = better at predicting who over/under-performs:")
    print(f"{'stat':6} {'A minutes out':>14} {'B share-based':>14} {'C role-weighted':>16}   avg boost C (when >0)")
    for s in STATS:
        y = df[f"delta_{s}"]
        cA, cB, cC = (np.corrcoef(y, df[c])[0, 1] for c in ("A_minutes_out", f"B_{s}", f"C_{s}"))
        pos = df[df[f"C_{s}"] > 0]
        slope = np.polyfit(pos[f"C_{s}"], pos[f"delta_{s}"], 1)[0] if len(pos) > 50 else float("nan")
        print(f"{s:6} {cA:14.3f} {cB:14.3f} {cC:16.3f}   predicted +{pos[f'C_{s}'].mean():.2f}, realised slope {slope:.2f}")
    return df


if __name__ == "__main__":
    main(sys.argv[1]).to_pickle(sys.argv[1].replace(".pkl", "_injury_redistribution.pkl"))
