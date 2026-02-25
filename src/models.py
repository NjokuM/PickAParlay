from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class NBAGame:
    game_id: str
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    game_date: str          # "YYYY-MM-DD"
    game_time_utc: str      # ISO UTC string
    odds_event_id: str      # The Odds API event ID (may be empty)


@dataclass
class PlayerProp:
    player_name: str
    nba_player_id: int
    market: str             # e.g. "player_points", "player_assists"
    line: float
    over_odds_decimal: float
    under_odds_decimal: float
    bookmaker: str          # e.g. "paddypower" or "best_available"
    game: NBAGame
    is_paddy_power: bool = True   # False = fell back to best available


@dataclass
class InjuryReport:
    player_name: str
    team: str
    status: str             # "out" | "doubtful" | "questionable" | "probable"


@dataclass
class FactorResult:
    name: str               # "Consistency", "vs Opponent", etc.
    score: float            # 0.0 – 100.0
    weight: float           # e.g. 0.38
    evidence: list[str]     # Human-readable bullet points for display
    data: dict              # Raw data for further processing
    confidence: float = 1.0  # 0.0–1.0 — penalised when sample is small


@dataclass
class ValuedProp:
    prop: PlayerProp
    value_score: float                  # 0–100 composite
    factors: list[FactorResult]
    recommendation: str                 # "Strong Value" | "Good Value" | "Marginal" | "Poor Value"
    backing_data: dict
    suspicious_line: bool = False       # True if line looks like a trap
    suspicious_reason: str = ""


@dataclass
class BetLeg:
    valued_prop: ValuedProp
    side: str               # "over" (always over for now)
    decimal_odds: float


@dataclass
class BetSlip:
    legs: list[BetLeg]
    combined_decimal_odds: float
    target_decimal_odds: float
    total_value_score: float
    summary: str
    has_correlated_legs: bool = False   # True if 2+ legs from same game


# Mapping entry: stat key → either a column name string or a callable on a row
@dataclass
class MarketMapping:
    market: str
    stat_key: str                           # display label
    compute: str | Callable                 # column name OR lambda
