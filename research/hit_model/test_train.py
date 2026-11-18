import json

import numpy as np
import pandas as pd

import train
from src.analysis import hit_model


def synthetic_dataset(n_dates=25, per_date=40, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range("2026-02-01", periods=n_dates).strftime("%Y-%m-%d"):
        for i in range(per_date):
            z = rng.normal()
            p_mkt = float(np.clip(rng.uniform(0.35, 0.65), 0.05, 0.95))
            true_p = 1 / (1 + np.exp(-(np.log(p_mkt / (1 - p_mkt)) + 0.5 * z - 0.2)))
            market = hit_model.MARKETS[i % len(hit_model.MARKETS)]
            rows.append({"player_id": i, "player": f"P{i}", "date": d, "market": market, "stat": "PTS", "line": 10.5,
                         "over_odds": 1 / p_mkt * 0.95, "under_odds": 1 / (1 - p_mkt) * 0.95, "over_hit": int(rng.random() < true_p),
                         "old_score_over": 60.0, "old_score_under": 50.0, "p_mkt_over": p_mkt, "team": "BOS", "opp": "NYK",
                         "mkt_logit": np.log(p_mkt / (1 - p_mkt)), "line_log": np.log(11), "z_season": z,
                         **{c: rng.normal() for c in hit_model.COMMON if c not in ("line_log", "z_season")},
                         "usg": rng.normal() if "points" in market else np.nan})
    return pd.DataFrame(rows)


def test_logistic_fit_recovers_signal():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(4000, 2))
    y = (rng.random(4000) < 1 / (1 + np.exp(-(1.5 * X[:, 0])))).astype(float)
    w = train.fit_logistic(X, y, l2=1.0)
    assert w[1] > 1.0 and abs(w[2]) < 0.2
    off = train.fit_logistic(X, y, l2=1.0, offset=np.full(4000, 0.5))
    assert off[0] < w[0]
    assert train.auc([0.1, 0.9], [0, 1]) == 1.0 and train.logloss(np.array([0.5]), np.array([1])) > 0


def test_train_exports_a_loadable_model(tmp_path):
    ds_path, out = tmp_path / "ds.pkl", tmp_path / "coefs.json"
    synthetic_dataset().to_pickle(ds_path)
    train.main(str(ds_path), str(out), "9.9")
    m = json.load(open(out))
    assert m["version"] == "9.9" and len(m["coef"]) == len(hit_model.design_columns(m["deep_features"]))
    assert "usg" in m["deep_features"] and m["special_edge_min"] in train.EDGE_GRID
    z_col = hit_model.COMMON.index("z_season")
    assert m["coef"][z_col] > 0                               # learned the real signal


def test_side_view_and_table():
    df = pd.DataFrame({"over_hit": [1, 0], "p_mkt_over": [0.5, 0.5], "over_odds": [1.9, 1.9], "under_odds": [1.9, 1.9]})
    sv = train.side_view(df, np.array([0.7, 0.3]))
    assert sv.hit.tolist() == [True, True] and sv.under.tolist() == [False, True]
    assert "hit" in train.table(sv)
