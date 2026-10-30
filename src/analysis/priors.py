"""
Early-season player priors.

With a handful of games, a player's current-season numbers are mostly noise.
Backtested on 2025-26 (predicting each player's next 15 games after their first
N): blending current-season games with LAST season's per-minute production ×
THIS season's minutes cut projection error from 34% to 29% at 5 games (39% →
31% at 3), and helped every subgroup — including players who changed team.
In the consistency factor it made hit rates far better calibrated (Brier
0.311 → 0.277 at 5 games; small-sample hit rates were worse than a coin flip)
and ranked props better (AUC 0.548 → 0.557). Per-minute rates
carry across seasons; minutes (role, new team) are what change, and those come
from the current season.

The prior is worth config.PLAYER_PRIOR_GAMES games and fades to nothing by
config.PLAYER_PRIOR_FADE_GAMES games played, so mid/late-season scoring is
unchanged. Rookies and barely-played players get no prior.
"""
from __future__ import annotations

import math
import time

import pandas as pd

import config
from src.api.nba_stats import get_league_player_totals

# Stat column → component columns summed for its per-minute rate
_COMPONENTS: dict[str, tuple[str, ...]] = {
    "PTS":  ("PTS",),
    "REB":  ("REB",),
    "AST":  ("AST",),
    "FG3M": ("FG3M",),
    "PRA":  ("PTS", "REB", "AST"),
    "PR":   ("PTS", "REB"),
    "PA":   ("PTS", "AST"),
    "RA":   ("REB", "AST"),
}

# In-process memo of {season: {player_id: prior}} — the league table is read
# once per process instead of once per prop. Failures back off for 10 minutes.
_tables: dict[str, dict[int, dict]] = {}
_failed_at: dict[str, float] = {}


def build_prior(totals: dict) -> dict | None:
    """Per-minute rates from one player's season-totals row, or None if too small a sample."""
    gp = int(totals.get("GP") or 0)
    minutes = float(totals.get("MIN") or 0.0)
    if gp < config.PLAYER_PRIOR_MIN_GP or minutes <= 0:
        return None
    rates = {
        stat: sum(float(totals.get(c) or 0.0) for c in comps) / minutes
        for stat, comps in _COMPONENTS.items()
    }
    return {"GP": gp, "MPG": minutes / gp, "rates": rates}


def get_player_prior(player_id: int, season: str | None = None) -> dict | None:
    """
    Prior from the season BEFORE `season` (default: the current season), i.e.
    last season's per-minute rates. None for rookies / players below
    PLAYER_PRIOR_MIN_GP last season / when the stats call fails.
    """
    prev = config.prev_season_of(season or config.DEFAULT_SEASON)
    table = _tables.get(prev)
    if table is None:
        if time.time() - _failed_at.get(prev, 0.0) < 600:
            return None
        df = get_league_player_totals(prev)
        if df.empty:
            _failed_at[prev] = time.time()
            return None
        table = {}
        for row in df.to_dict(orient="records"):
            prior = build_prior(row)
            if prior:
                table[int(row["PLAYER_ID"])] = prior
        _tables[prev] = table
    return table.get(int(player_id))


def prior_weight(games_played: int, prior: dict | None) -> float:
    """How many games the prior counts as, given current-season games played."""
    if not prior:
        return 0.0
    fade = max(0.0, 1.0 - games_played / config.PLAYER_PRIOR_FADE_GAMES)
    reliability = min(1.0, prior["GP"] / config.PLAYER_PRIOR_FULL_GP)
    return config.PLAYER_PRIOR_GAMES * fade * reliability


def prior_mean(prior: dict, stat_col: str, df: pd.DataFrame) -> float | None:
    """Last season's per-minute rate × this season's minutes per game."""
    rate = prior["rates"].get(stat_col)
    if rate is None or df.empty or "MIN" not in df.columns:
        return None
    mpg = float(pd.to_numeric(df["MIN"], errors="coerce").mean())
    if not mpg or math.isnan(mpg):
        return None
    return rate * mpg


# ---------------------------------------------------------------------------
# Negative-binomial helpers — turn a projected mean into hit probabilities
# ---------------------------------------------------------------------------

def _dispersion(mu: float, stat_col: str) -> float:
    """NB dispersion r matching config.STAT_SD_POWER's SD at this mean (Var = mu + mu²/r)."""
    a, b = config.STAT_SD_POWER.get(stat_col, (2.0, 0.4))
    excess = (a * mu ** b) ** 2 - mu
    return mu * mu / excess if excess > 1e-6 else 1e6   # ~Poisson when not overdispersed


def _pmf_terms(mu: float, r: float):
    """Yield NB pmf(0), pmf(1), … for mean mu and dispersion r (Var = mu + mu²/r)."""
    p = r / (r + mu)
    term = math.exp(r * math.log(p))
    j = 0
    while True:
        yield term
        term *= (j + r) / (j + 1) * (1 - p)
        j += 1


def _cdf(x: int, mu: float, r: float) -> float:
    if x < 0:
        return 0.0
    if mu <= 0:
        return 1.0
    total = 0.0
    for j, term in enumerate(_pmf_terms(mu, r)):
        total += term
        if j >= x:
            break
    return min(1.0, total)


def prob_hit(mu: float, stat_col: str, line: float, side: str = "over") -> float:
    """P(stat > line) for OVER, P(stat < line) for UNDER, given projected mean mu."""
    if mu <= 0:
        return 0.0 if side == "over" else 1.0
    r = _dispersion(mu, stat_col)
    if side == "under":
        return _cdf(math.ceil(line) - 1, mu, r)
    return 1.0 - _cdf(math.floor(line), mu, r)


def quantile(mu: float, stat_col: str, q: float) -> int:
    """Smallest x with P(stat <= x) >= q."""
    if mu <= 0:
        return 0
    r = _dispersion(mu, stat_col)
    total = 0.0
    for j, term in enumerate(_pmf_terms(mu, r)):
        total += term
        if total >= q or j > 400:
            return j
    return 0
