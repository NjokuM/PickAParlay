"""
Train the pooled hit-probability model and export it for live grading
(src/analysis/hit_model_coefs.json). Design matrix: src/analysis/hit_model.py.

    python research/hit_model/train.py <dataset.pkl> <out_coefs.json> [version]

Honest evaluation: the regularisation strength and the special-pick edge
threshold are chosen on a FORWARD split (train on the earlier 60% of dates,
test on the later 40%) — the situation the model faces live. The exported
model is then refit on all dates, with Platt calibration from date-grouped
out-of-fold predictions so the score reads as a hit chance.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.analysis.hit_model import COMMON, design_row  # noqa: E402

EXCLUDED = {"gp_log"}   # see src/analysis/hit_model.COMMON
NON_FEATURES = {"player_id", "player", "date", "market", "stat", "line", "over_odds", "under_odds",
                "over_hit", "old_score_over", "old_score_under", "p_mkt_over", "team", "opp"}
L2_GRID = (30.0, 100.0, 300.0, 1000.0, 3000.0)
EDGE_GRID = (0.02, 0.03, 0.04, 0.05, 0.06, 0.08)


def fit_logistic(X, y, l2, iters=60, offset=None):
    """L2-regularised logistic regression (intercept unpenalised), Newton's method, optional offset."""
    X1 = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X1.shape[1])
    off = np.zeros(len(X)) if offset is None else offset
    pen = np.r_[0.0, np.full(X.shape[1], l2)]
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(off + X1 @ w, -30, 30)))
        step = np.linalg.solve(-(X1.T * (p * (1 - p))) @ X1 - np.diag(pen), X1.T @ (y - p) - pen * w)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def logit_of(X, w):
    return w[0] + X @ w[1:]


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def auc(score, y):
    score, y = np.asarray(score, float), np.asarray(y, bool)
    ranks = pd.Series(score).rank().values
    pos, neg = y.sum(), (~y).sum()
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def fit_scale(df, deep):
    scale = {c: (float(df[c].mean()), float(df[c].std() or 1.0)) for c in COMMON}
    for c in deep:
        v = df[c].dropna()
        scale[c] = (float(v.mean()), float(v.std() or 1.0))
    return scale


def design(df, scale, deep):
    recs = df[COMMON + deep].to_dict("records")
    rows = [design_row(m, {k: v for k, v in r.items() if v == v}, scale, deep)   # v == v drops NaN
            for m, r in zip(df.market, recs)]
    return np.array(rows)


def side_view(df, p_over):
    over = p_over >= 0.5
    return pd.DataFrame({
        "p": np.where(over, p_over, 1 - p_over),
        "hit": np.where(over, df.over_hit.values == 1, df.over_hit.values == 0),
        "p_mkt": np.where(over, df.p_mkt_over.values, 1 - df.p_mkt_over.values),
        "odds": np.where(over, df.over_odds.values, df.under_odds.values),
        "under": ~over,
    })


def table(sv, edges=(0.0, 0.52, 0.55, 0.58, 0.62, 0.66, 1.01)):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = sv[(sv.p >= lo) & (sv.p < hi)]
        if len(b):
            out.append(f"    {lo*100:3.0f}-{min(hi, 1)*100:3.0f}: n={len(b):5}  hit {b.hit.mean()*100:5.1f}%"
                       f"  ROI {np.where(b.hit, b.odds - 1, -1).mean()*100:+6.1f}%")
    return "\n".join(out)


def oof_logits(df, scale, deep, l2, folds=5):
    dates = np.array(sorted(df.date.unique()))
    z = np.zeros(len(df))
    for grp in np.array_split(dates, folds):
        test = df.date.isin(grp).values
        sc = fit_scale(df[~test], deep)
        w = fit_logistic(design(df[~test], sc, deep), df.over_hit.values[~test].astype(float), l2, offset=df.mkt_logit.values[~test])
        z[test] = logit_of(design(df[test], sc, deep), w)   # adjustment only
    return z


def main(dataset_path, out_path, version="3.0"):
    df = pd.read_pickle(dataset_path).reset_index(drop=True)
    deep = sorted(c for c in df.columns if c not in NON_FEATURES and c not in COMMON and c not in EXCLUDED and c != "mkt_logit")
    y = df.over_hit.values.astype(float)
    dates = sorted(df.date.unique())
    cut = dates[int(len(dates) * 0.6)]
    tr, te = df[df.date < cut], df[df.date >= cut]
    print(f"{len(df)} lines over {len(dates)} dates. Forward test: train {tr.date.min()}→{tr.date.max()} ({len(tr)}), "
          f"test {te.date.min()}→{te.date.max()} ({len(te)})\n")

    # ── choose l2 on the forward split ──────────────────────────────────
    sc = fit_scale(tr, deep)
    Xtr, Xte = design(tr, sc, deep), design(te, sc, deep)
    best = None
    for l2 in L2_GRID:
        w = fit_logistic(Xtr, tr.over_hit.values.astype(float), l2, offset=tr.mkt_logit.values)
        p = sigmoid(te.mkt_logit.values + logit_of(Xte, w)); sv = side_view(te, p)
        a, ll = auc(sv.p, sv.hit), logloss(p, te.over_hit.values)
        print(f"  l2={l2:6.0f}: forward AUC {a:.3f}  log-loss {ll:.4f}")
        if best is None or a > best[1] + 0.001 or (abs(a - best[1]) <= 0.001 and ll < best[2]):
            best = (l2, a, ll)
    l2 = best[0]
    print(f"  → l2 = {l2:.0f}\n")

    # ── forward test, calibrated on the training period only ───────────
    z_tr_oof = oof_logits(tr, sc, deep, l2)
    cal_w = fit_logistic(z_tr_oof.reshape(-1, 1), tr.over_hit.values.astype(float), 0.0, offset=tr.mkt_logit.values)
    w = fit_logistic(Xtr, tr.over_hit.values.astype(float), l2, offset=tr.mkt_logit.values)
    p_te = sigmoid(te.mkt_logit.values + cal_w[0] + cal_w[1] * logit_of(Xte, w))
    sv = side_view(te, p_te)
    print(f"FORWARD TEST (later weeks, never seen): AUC {auc(sv.p, sv.hit):.3f}  log-loss {logloss(p_te, te.over_hit.values):.4f}")
    print("  hit rate by score (score = chance of hitting):\n" + table(sv))
    sv["edge"] = sv.p - sv.p_mkt
    print("  special picks — model chance beats the market's no-vig chance by:")
    edge_pick, best_roi = EDGE_GRID[-1], float("-inf")
    for e in EDGE_GRID:
        b = sv[sv.edge >= e]
        roi = np.where(b.hit, b.odds - 1, -1).mean() * 100 if len(b) else float("nan")
        print(f"    ≥{e*100:2.0f}pp: n={len(b):5} ({len(b)/te.date.nunique():4.1f}/night)  hit {b.hit.mean()*100:5.1f}%"
              f"  market said {b.p_mkt.mean()*100:5.1f}%  ROI {roi:+6.1f}%  ({b.under.mean():.0%} unders)")
        if len(b) >= 300 and roi > best_roi:     # most profitable threshold with a real sample
            edge_pick, best_roi = e, roi
    print(f"  → special-pick threshold: edge ≥ {edge_pick*100:.0f}pp\n")

    # ── final model on all dates ────────────────────────────────────────
    scale = fit_scale(df, deep)
    w = fit_logistic(design(df, scale, deep), y, l2, offset=df.mkt_logit.values)
    z_oof = oof_logits(df, scale, deep, l2)
    cal = fit_logistic(z_oof.reshape(-1, 1), y, 0.0, offset=df.mkt_logit.values)
    sv_all = side_view(df, sigmoid(df.mkt_logit.values + cal[0] + cal[1] * z_oof))
    print(f"ALL DATES, out-of-fold by date: AUC {auc(sv_all.p, sv_all.hit):.3f}")
    print(table(sv_all))

    model = {
        "version": version, "trained_at": date.today().isoformat(), "rows": int(len(df)),
        "dates": [df.date.min(), df.date.max()], "l2": l2, "deep_features": deep,
        "scale": {k: [round(m, 6), round(s, 6)] for k, (m, s) in scale.items()},
        "intercept": round(float(w[0]), 6), "coef": [round(float(c), 6) for c in w[1:]],
        "calibration": [round(float(cal[0]), 6), round(float(cal[1]), 6)],
        "special_edge_min": edge_pick,
        "forward_test": {"auc": round(auc(sv.p, sv.hit), 4), "dates": [te.date.min(), te.date.max()], "n": int(len(te))},
    }
    json.dump(model, open(out_path, "w"), indent=1)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
