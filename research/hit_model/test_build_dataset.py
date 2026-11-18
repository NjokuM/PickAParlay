import pickle

import pandas as pd

import build_dataset as bd


def test_load_lines_one_row_per_line(graded_props_file):
    lines = bd.load_lines(str(graded_props_file), None)
    assert not lines.empty and lines.duplicated(["player_id", "date", "market", "line"]).sum() == 0
    assert lines.p_mkt_over.between(0, 1).all()
    early = bd.load_lines(str(graded_props_file), sorted(lines.date)[0])
    assert set(early.date) == {sorted(lines.date)[0]}             # last_date cuts off later games


def test_build_dataset_end_to_end(tmp_path, season_log, graded_props_file, fake_snapshot):
    log_path, snap_path, out = tmp_path / "log.pkl", tmp_path / "snaps.pkl", tmp_path / "ds.pkl"
    season_log.to_pickle(log_path)
    dates = sorted(pd.read_json(graded_props_file).game_date.astype(str).str[:10].unique())
    pickle.dump({d: fake_snapshot for d in dates}, open(snap_path, "wb"))
    bd.main("2025-26", str(graded_props_file), str(log_path), str(snap_path), str(out))
    ds = pd.read_pickle(out)
    assert len(ds) > 20 and {"over_hit", "mkt_logit", "z_season", "teammates_out", "role_minutes"} <= set(ds.columns)
    assert ds.teammates_out.abs().sum() > 0                    # player 0's absences show up for teammates
