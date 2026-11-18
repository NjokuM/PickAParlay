"""
Builders for test data (game logs, props, graded props), shared by the
test files next to each module. Fixtures live in conftest.py.
"""


def build_log(values=None, stat="PTS", n=None, minutes=30.0, team="BOS",
              opp="NYK", start="2026-03-31", every=2, home_pattern=None, **const):
    """
    A player game log like nba_api's PlayerGameLog: newest game first,
    GAME_DATE as datetimes, MATCHUP "BOS vs. NYK" (home) / "BOS @ NYK" (away),
    plus PTS/REB/AST/FG3M/FG3A/FGA/FTA/MIN and the combo columns.
    `values` sets `stat` per game (newest first); other stats get defaults.
    """
    import pandas as pd
    values = list(values) if values is not None else [20.0] * (n or 10)
    n = len(values)
    dates = pd.date_range(end=pd.Timestamp(start), periods=n, freq=f"{every}D")[::-1]
    home = home_pattern or [i % 2 == 0 for i in range(n)]
    df = pd.DataFrame({
        "GAME_DATE": dates,
        "Game_ID": [f"00226{i:05d}" for i in range(n)],
        "MATCHUP": [f"{team} vs. {opp}" if h else f"{team} @ {opp}" for h in home],
        "MIN": [minutes] * n,
        "PTS": [20.0] * n, "REB": [6.0] * n, "AST": [4.0] * n,
        "FG3M": [2.0] * n, "FG3A": [5.0] * n, "FGA": [15.0] * n, "FTA": [4.0] * n, "FGM": [7.0] * n,
    })
    df[stat] = values
    for k, v in const.items():
        df[k] = v
    df["PRA"] = df.PTS + df.REB + df.AST
    df["PR"] = df.PTS + df.REB
    df["PA"] = df.PTS + df.AST
    df["RA"] = df.REB + df.AST
    return df


def make_prop(market="player_points", line=20.5, over=1.9, under=1.9, player_id=7, name="Jane Doe",
              home="BOS", away="NYK", event_id="evt"):
    from src.models import NBAGame, PlayerProp
    game = NBAGame("0022600001", home, away, 1610612738, 1610612752, "2026-04-01", "2026-04-01T23:00:00Z", event_id)
    return PlayerProp(name, player_id, market, line, over, under, "fanduel", game)


def make_vp(name="Jane Doe", market="player_points", line=20.5, score=70.0, odds=1.9, under_odds=1.9,
            side="over", home="BOS", away="NYK", bookmaker="fanduel", paddy=False, pid=7, factors=None):
    """A graded prop (ValuedProp) for slip, display and database tests."""
    from src.models import FactorResult, ValuedProp
    prop = make_prop(market=market, line=line, over=odds, under=under_odds, player_id=pid, name=name, home=home, away=away)
    prop.bookmaker, prop.is_paddy_power = bookmaker, paddy
    factors = factors or [FactorResult("Consistency", score, 0.3, ["Last 5 games: 1, 2"], {"hit_rate": 0.6}, 1.0),
                          FactorResult("Opponent Defense", 60.0, 0.15, ["weak defence"], {}, 1.0)]
    return ValuedProp(prop=prop, value_score=score, factors=factors, recommendation="Good Value",
                      backing_data={"side": side, "season_avg": 22.0, "hit_probability": 0.56,
                                    "market_probability": 0.52, "edge": 0.04, "is_special": False})
