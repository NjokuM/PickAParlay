"""
Central configuration: weights, market mappings, thresholds, constants.
All tunable parameters live here — nothing is hardcoded in modules.
"""
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv(override=True)  # .env always wins over any pre-existing shell env vars


# ---------------------------------------------------------------------------
# NBA Season auto-detection
# The NBA regular season starts in October each year.
#   Oct / Nov / Dec  → season beginning this calendar year  (e.g. Oct 2025 → "2025-26")
#   Jan – Sep        → season that started last calendar year (e.g. Feb 2026 → "2025-26")
# ---------------------------------------------------------------------------
def _nba_season(year_offset: int = 0) -> str:
    """
    Return the NBA season string for the current (or offset) season.
    year_offset=0  → current season  (e.g. "2025-26")
    year_offset=-1 → previous season (e.g. "2024-25")
    """
    today = date.today()
    base = today.year if today.month >= 10 else today.year - 1
    start = base + year_offset
    return f"{start}-{str(start + 1)[2:]}"


DEFAULT_SEASON: str = _nba_season(0)    # e.g. "2025-26"
PREV_SEASON:    str = _nba_season(-1)   # e.g. "2024-25"

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")

# ---------------------------------------------------------------------------
# Factor weights — must sum to 1.0
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS: dict[str, float] = {
    "consistency":      0.38,   # Floor analysis + recency-weighted hit rate (last 10 games)
    "vs_opponent":      0.20,   # Performance vs tonight's specific opponent (H2H)
    "home_away":        0.12,   # Home/away split matched to tonight's location
    "injury":           0.13,   # Player health + opponent injury advantage
    "team_context":     0.07,   # Team pace, recent form, rest
    "season_avg":       0.04,   # Current season averages vs the prop line (was 0.06)
    "blowout_risk":     0.02,   # Spread + H2H margin — risk of early DNP (was 0.03)
    "line_value":       0.00,   # Absorbed into volume_context (was 0.01)
    "volume_context":   0.04,   # Minutes trend + FGA/assist-rate for the market
}

assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 0.001, "Weights must sum to 1.0"

# ---------------------------------------------------------------------------
# Recency weights for last-N games (most recent first, sum = 1.0)
# ---------------------------------------------------------------------------
RECENCY_WEIGHTS_10: list[float] = [0.20, 0.18, 0.15, 0.12, 0.10, 0.08, 0.06, 0.04, 0.04, 0.03]

# ---------------------------------------------------------------------------
# Minimum sample sizes for confidence scoring
# Below these thresholds the factor score is blended toward a neutral 50
# ---------------------------------------------------------------------------
MIN_SAMPLE: dict[str, int] = {
    "consistency":  5,
    "vs_opponent":  4,
    "home_away":    6,
    "injury":       1,    # always at least 1 (injury report itself)
    "team_context": 5,
    "season_avg":   10,
    "blowout_risk": 1,
    "line_value":   1,
}

# ---------------------------------------------------------------------------
# Context similarity weights
# Used by context_filter to down-weight non-current-team games
# ---------------------------------------------------------------------------
CONTEXT_WEIGHTS = {
    "current_team":          1.00,
    "previous_team":         0.15,   # Mid-season trade: use with care
    "vs_opponent_current":   1.00,
    "vs_opponent_last_szn":  0.40,
    "vs_opponent_older":     0.05,
    "home_tonight_home":     1.00,
    "home_tonight_away":     0.00,   # Excluded
    "b2b_tonight_b2b":       1.00,
    "normal_rest_b2b":       0.30,
}

# Minimum current-team games before we stop using previous-team data at all
MIN_CURRENT_TEAM_GAMES: int = 15

# ---------------------------------------------------------------------------
# Market → stat computation mapping
# 'compute' is either a column name string or a lambda that takes a pandas row
# ---------------------------------------------------------------------------
MARKET_MAP: dict[str, dict] = {
    "player_points": {
        "stat_key": "PTS",
        "compute":  "PTS",
        "label":    "Points",
    },
    "player_assists": {
        "stat_key": "AST",
        "compute":  "AST",
        "label":    "Assists",
    },
    "player_rebounds": {
        "stat_key": "REB",
        "compute":  "REB",
        "label":    "Rebounds",
    },
    "player_threes": {
        "stat_key": "FG3M",
        "compute":  "FG3M",
        "label":    "3-Pointers Made",
    },
    "player_blocks": {
        "stat_key": "BLK",
        "compute":  "BLK",
        "label":    "Blocks",
    },
    "player_steals": {
        "stat_key": "STL",
        "compute":  "STL",
        "label":    "Steals",
    },
    "player_turnovers": {
        "stat_key": "TOV",
        "compute":  "TOV",
        "label":    "Turnovers",
    },
    "player_points_rebounds_assists": {
        "stat_key": "PRA",
        "compute":  lambda row: row["PTS"] + row["REB"] + row["AST"],
        "label":    "Pts+Reb+Ast",
    },
    "player_points_rebounds": {
        "stat_key": "PR",
        "compute":  lambda row: row["PTS"] + row["REB"],
        "label":    "Pts+Reb",
    },
    "player_points_assists": {
        "stat_key": "PA",
        "compute":  lambda row: row["PTS"] + row["AST"],
        "label":    "Pts+Ast",
    },
    "player_rebounds_assists": {
        "stat_key": "RA",
        "compute":  lambda row: row["REB"] + row["AST"],
        "label":    "Reb+Ast",
    },
}

# ---------------------------------------------------------------------------
# Value scoring thresholds
# ---------------------------------------------------------------------------
SCORE_LABELS: list[tuple[float, str]] = [
    (80.0, "Strong Value"),
    (65.0, "Good Value"),
    (50.0, "Marginal Value"),
    (0.0,  "Poor Value"),
]

MIN_VALUE_SCORE: float = 50.0   # Props below this are excluded from slips

# ---------------------------------------------------------------------------
# Bet builder
# ---------------------------------------------------------------------------
MAX_LEGS: int = 6
MIN_LEGS: int = 2
ODDS_TOLERANCE: float = 0.20    # ±20% of target decimal odds
MAX_PROPS_IN_SEARCH: int = 40   # Top N by value_score used in combo search
MAX_SLIPS_RETURNED: int = 5

# Correlation penalties (multiplied into independence score)
SAME_PLAYER_PENALTY: float = 0.80
SAME_GAME_PENALTY:   float = 0.90

# ---------------------------------------------------------------------------
# Blowout risk thresholds
# ---------------------------------------------------------------------------
BLOWOUT_SPREAD_NORMALISER: float = 20.0    # spread of 20 = 1.0 risk
BLOWOUT_RISK_CUTOFF: float = 0.70          # above this, counting props penalised
BLOWOUT_PENALTY_UNDERDOG_STAR: float = 0.25
BLOWOUT_PENALTY_FAVORITE_STAR: float = 0.15
BLOWOUT_PENALTY_BENCH:         float = 0.35
BLOWOUT_PENALTY_NON_COUNTING:  float = 0.08

# ---------------------------------------------------------------------------
# Suspicious line detection
# ---------------------------------------------------------------------------
SUSPICIOUS_EASY_THRESHOLD: float = 0.30    # line > 30% below season avg → flag
SUSPICIOUS_HARD_THRESHOLD: float = 0.30    # line > 30% above season avg → flag

# ---------------------------------------------------------------------------
# API settings
# ---------------------------------------------------------------------------
ODDS_API_BASE_URL: str = "https://api.the-odds-api.com/v4"
ODDS_SPORT: str = "basketball_nba"
ODDS_REGIONS: str = "eu"          # Paddy Power is EU region
ODDS_MARKETS_GAME: str = "h2h,spreads"
PREFERRED_BOOKMAKER: str = "paddypower"

ESPN_INJURY_URL: str = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
)

NBA_API_SLEEP: float = 0.6         # seconds between nba_api calls

# ---------------------------------------------------------------------------
# Cache TTLs (seconds)
# ---------------------------------------------------------------------------
CACHE_TTL: dict[str, int] = {
    "games":        43200,    # 12 hours
    "game_log":     86400,    # 24 hours (historical, doesn't change intra-day)
    "injuries":     2700,     # 45 minutes
    "props":        7200,     # 2 hours
    "team_stats":   86400,    # 24 hours
    "h2h":          86400,    # 24 hours
    "player_team":  43200,    # 12 hours — shorter than game_log so trades are caught same-day
}

CACHE_DIR: str = os.path.join(os.path.dirname(__file__), ".cache")
DATABASE_PATH: str = os.path.join(os.path.dirname(__file__), "pickaparlay.db")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# How many minutes before tip-off to stop showing a game
TIP_OFF_BUFFER_MINUTES: int = 30

# Minimum games played to include a player in analysis
MIN_GAMES_PLAYED: int = 5

# Season rolling window for role-change detection
ROLE_CHANGE_WINDOW: int = 20        # games
ROLE_CHANGE_THRESHOLD: float = 0.15  # if rolling-20 avg differs from full season avg by >15%
