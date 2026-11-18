import injury_redistribution as ir


def test_redistribution_analysis_runs(tmp_path, season_log):
    path = tmp_path / "log.pkl"
    season_log.to_pickle(path)
    df = ir.main(str(path))
    assert not df.empty and {"delta_PTS", "A_minutes_out", "B_PTS", "C_PTS", "base_MIN"} <= set(df.columns)
    assert (df.gp >= 10).all()
    assert ir.profile(season_log[season_log.PLAYER_ID == 1]).shape == (4,)
