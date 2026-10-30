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


def prev_season_of(season: str) -> str:
    """"2026-27" → "2025-26"."""
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[2:]}"

# ---------------------------------------------------------------------------
# Playoff detection & blending
# ---------------------------------------------------------------------------
PLAYOFF_GAME_WEIGHT: float = 1.35   # Playoff games count 35% more than RS games in all factor calcs

def is_playoffs() -> bool:
    """Auto-detect NBA playoffs — April through June."""
    return date.today().month in (4, 5, 6)

# ---------------------------------------------------------------------------
# API Keys — supports a pool of keys for automatic rotation
# Set ODDS_API_KEYS="key1,key2,key3" or fall back to single ODDS_API_KEY
# ---------------------------------------------------------------------------
def _parse_api_keys() -> list[str]:
    multi = os.getenv("ODDS_API_KEYS", "")
    if multi:
        return [k.strip() for k in multi.split(",") if k.strip()]
    single = os.getenv("ODDS_API_KEY", "")
    return [single] if single else []

ODDS_API_KEYS: list[str] = _parse_api_keys()
ODDS_API_KEY: str = ODDS_API_KEYS[0] if ODDS_API_KEYS else ""  # backwards compat

# ---------------------------------------------------------------------------
# Factor weights — must sum to 1.0
# ---------------------------------------------------------------------------
FACTOR_WEIGHTS: dict[str, float] = {
    "consistency":       0.30,   # Floor/ceiling + recency-weighted hit rate + mean (+9.7pp signal)
    "opponent_defense":  0.15,   # Opposing team defensive quality + pace adjustment (+19.7pp signal)
    "vs_opponent":       0.12,   # Performance vs tonight's specific opponent (H2H) (+2.0pp)
    "home_away":         0.10,   # Home/away split matched to tonight's location (+7.1pp)
    "injury":            0.10,   # Player health + teammate/opponent injury context
    "blowout_risk":      0.10,   # Spread + H2H margin — risk of early DNP (+9.9pp signal)
    "volume_context":    0.07,   # Minutes trend + FGA/assist-rate, direction-aware
    "season_avg":        0.06,   # Current season averages vs the prop line (+8.0pp)
    "line_value":        0.00,   # Retired (absorbed into volume_context)
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
    "consistency":       5,
    "opponent_defense":  1,    # always available (league-wide team stats)
    "vs_opponent":       4,
    "home_away":         6,
    "injury":            1,    # always at least 1 (injury report itself)
    "season_avg":        10,
    "blowout_risk":      1,
    "line_value":        1,
}

# ---------------------------------------------------------------------------
# Early-season priors (src/analysis/priors.py)
# A handful of games is mostly noise. Backtested on 2025-26 (predict each
# player's next 15 games from their first N): blending current-season games
# with LAST season's per-minute rates × THIS season's minutes cut error from
# 34% to 29% at 5 games (39% → 31% at 3), and helped every subgroup incl.
# players who changed team — per-minute production carries over, minutes
# (role/team) are what change and they come from this season. Even when early
# games sharply contradict the prior, trusting the prior was far better (the
# early games are usually the fluke). Team "allowed" ranks after 5 games
# barely predict the rest of the season (AST 0.20, 3PM 0.15 rank correlation)
# — last season's ranks do better until ~15 games in.
# Both priors fade to zero, so mid/late-season scoring is unchanged.
# ---------------------------------------------------------------------------
PLAYER_PRIOR_GAMES: float = 10.0      # prior counts as this many games at season start…
PLAYER_PRIOR_FADE_GAMES: int = 40     # …shrinking linearly to 0 by this many games played
PLAYER_PRIOR_FULL_GP: int = 20        # last-season GP needed for a full-strength prior
PLAYER_PRIOR_MIN_GP: int = 10         # below this (rookies, barely played) → no prior

TEAM_PRIOR_GAMES: float = 25.0        # last season's team profile counts as this many games…
TEAM_PRIOR_FADE_GAMES: int = 45       # …shrinking linearly to 0 by this many games played
TEAM_FULL_CONFIDENCE_GAMES: int = 30  # team-stat factors reach full confidence here

# Game-to-game spread per stat: SD = a × mean^b — turns a projected mean into
# P(over/under line) via a negative binomial. Fitted on 2024-25 player game
# logs; spread grows slower than the mean (a 28-ppg star varies ±8, not ±10).
STAT_SD_POWER: dict[str, tuple[float, float]] = {
    "PTS":  (2.708, 0.338),
    "REB":  (1.274, 0.466),
    "AST":  (1.140, 0.493),
    "FG3M": (1.104, 0.466),
    "PRA":  (4.058, 0.234),
    "PR":   (3.597, 0.260),
    "PA":   (3.079, 0.300),
    "RA":   (1.734, 0.356),
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

# Consistency also needs this many games of evidence (games played + prior
# games) for full confidence — a 4/5 streak alone isn't, unless a prior backs it.
CONSISTENCY_FULL_CONFIDENCE_GAMES: int = 10

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
ODDS_REGIONS: str = "eu"                     # Primary region for core markets (Bet365/PP)
ODDS_REGIONS_US: str = "us"                  # US-only combo markets (PR, PA, RA)
ALTERNATE_ODDS_REGIONS: str = "us"          # Alternate lines only offered by US books (FanDuel, DraftKings etc)

# Markets that EU bookmakers (Bet365/PP) cover
EU_MARKETS: list[str] = [
    "player_points", "player_assists", "player_rebounds",
    "player_threes", "player_points_rebounds_assists",
]
# Markets only available from US bookmakers — use clean single-line books
# (Bovada sends 3 lines per player causing odds mismatches)
US_ONLY_MARKETS: list[str] = [
    "player_points_rebounds", "player_points_assists", "player_rebounds_assists",
]
US_COMBO_BOOKMAKERS: str = "fanduel,draftkings"
ODDS_MARKETS_GAME: str = "h2h,spreads"
PREFERRED_BOOKMAKER: str = "bet365"
FALLBACK_BOOKMAKER: str = "paddypower"

ESPN_INJURY_URL: str = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
)

NBA_API_SLEEP: float = 0.0         # no delay — 24h cache means most calls are instant hits

# ---------------------------------------------------------------------------
# Cache TTLs (seconds)
# ---------------------------------------------------------------------------
CACHE_TTL: dict[str, int] = {
    "games":        43200,    # 12 hours
    "game_log":     21600,    # 6 hours — ensures B2B games are picked up on next-day refresh
    "injuries":     2700,     # 45 minutes
    "props":        7200,     # 2 hours (used for cache key, but smart refresh invalidates before fetching)
    "events":       28800,    # 8 hours — game list doesn't change intra-day
    "spreads":      28800,    # 8 hours — spreads barely move, only used for blowout risk (1% weight)
    "team_stats":   86400,    # 24 hours
    "h2h":          86400,    # 24 hours
    "player_team":  43200,    # 12 hours — shorter than game_log so trades are caught same-day
    "prev_season":  604800,   # 7 days — a finished season's data doesn't change
}

CACHE_DIR: str = os.getenv("CACHE_DIR", os.path.join(os.path.dirname(__file__), ".cache"))
DATABASE_PATH: str = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "pickaparlay.db"))

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# How many minutes before tip-off to stop showing a game
TIP_OFF_BUFFER_MINUTES: int = 30

# Minimum games played to include a player in analysis
MIN_GAMES_PLAYED: int = 5
# …relaxed when a last-season prior exists (3 games + prior beat 5 games alone in backtest)
MIN_GAMES_WITH_PRIOR: int = 3

# Season rolling window for role-change detection
ROLE_CHANGE_WINDOW: int = 20        # games
ROLE_CHANGE_THRESHOLD: float = 0.15  # if rolling-20 avg differs from full season avg by >15%

# ---------------------------------------------------------------------------
# Alternate market keys (for Ladder Challenge)
# All 11 alternate markets available from The Odds API
# ---------------------------------------------------------------------------
ALTERNATE_MARKET_MAP: list[str] = [
    "player_points_alternate",
    "player_assists_alternate",
    "player_rebounds_alternate",
    "player_threes_alternate",
    "player_points_rebounds_assists_alternate",
    "player_points_rebounds_alternate",
    "player_points_assists_alternate",
    "player_rebounds_assists_alternate",
]

# Ladder Challenge — combined parlay odds window (decimal)
LADDER_ODDS_MIN: float = 1.95
LADDER_ODDS_MAX: float = 2.30
LADDER_ODDS_TARGET: float = 2.125       # midpoint used for build_slips
LADDER_ODDS_TOLERANCE: float = 0.15    # ±15% around 2.125 → wider search for 3-4 leg combos

# Ladder Challenge — per-leg odds window (≈ 1/7 to 2/5 fractional)
LADDER_LEG_ODDS_MIN: float = 1.15
LADDER_LEG_ODDS_MAX: float = 1.45
LADDER_LEG_COUNTS: list[int] = [3, 4]   # only build 3 or 4 leg slips
LADDER_FLOOR_BUFFER: float = 1.5        # alt line must be ≥ floor + this buffer

# Useful odds range for alternate prop filtering (exclude junk lines)
ALTERNATE_ODDS_MIN: float = 1.10
ALTERNATE_ODDS_MAX: float = 2.60


# ---------------------------------------------------------------------------
# Market-key helpers — normalise _alternate suffix for MARKET_MAP lookups
# ---------------------------------------------------------------------------

def get_base_market(market: str) -> str:
    """Strip _alternate suffix to get the base market key for MARKET_MAP lookups."""
    return market.replace("_alternate", "")


def get_market_label(market: str) -> str:
    """Get human-readable label for a market key, handling _alternate suffix."""
    base = get_base_market(market)
    cfg = MARKET_MAP.get(base)
    return cfg["label"] if cfg else market
