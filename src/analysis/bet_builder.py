"""
Bet builder — combination search.
Takes all scored ValuedProps and finds the best N-leg combinations
that land closest to the user's target odds.
"""
from __future__ import annotations

import math
from itertools import combinations

import config
from src.models import ValuedProp, BetLeg, BetSlip


def build_slips(
    valued_props: list[ValuedProp],
    target_decimal: float,
    n_legs: int | None = None,
    min_score: float | None = None,
    bookmaker: str | None = None,
) -> list[BetSlip]:
    """
    Main entry point.

    valued_props: all scored props (already includes score < MIN_VALUE_SCORE filtered out upstream)
    target_decimal: e.g. 5.0 for a 4/1 bet
    n_legs: if specified, only build slips of exactly this length
    min_score: optional override for minimum value score cutoff
    bookmaker: if set, only include props from this bookmaker.
               "paddypower" matches is_paddy_power=True; any other string matches
               prop.bookmaker exactly. None = no filter.
    Returns top MAX_SLIPS_RETURNED slips sorted by slip_score descending.
    """
    # --- Bookmaker filter ---
    if bookmaker:
        if bookmaker.lower() == "paddypower":
            valued_props = [vp for vp in valued_props if vp.prop.is_paddy_power]
        else:
            valued_props = [vp for vp in valued_props if vp.prop.bookmaker == bookmaker.lower()]

    threshold = min_score if min_score is not None else config.MIN_VALUE_SCORE
    eligible = [vp for vp in valued_props if vp.value_score >= threshold]
    eligible.sort(key=lambda vp: vp.value_score, reverse=True)

    # Cap search space
    eligible = eligible[: config.MAX_PROPS_IN_SEARCH]

    if not eligible:
        return []

    if n_legs is not None:
        leg_counts = [n_legs]
    else:
        leg_counts = _estimate_leg_counts(eligible, target_decimal)

    all_slips: list[BetSlip] = []

    for n in leg_counts:
        if n < config.MIN_LEGS or n > config.MAX_LEGS:
            continue
        slips = _search_combinations(eligible, target_decimal, n)
        all_slips.extend(slips)

    # Deduplicate by frozenset of (player, market, side) tuples
    seen: set[frozenset] = set()
    unique_slips: list[BetSlip] = []
    for slip in sorted(all_slips, key=lambda s: s.total_value_score, reverse=True):
        key = frozenset(
            (leg.valued_prop.prop.player_name, leg.valued_prop.prop.market, leg.side)
            for leg in slip.legs
        )
        if key not in seen:
            seen.add(key)
            unique_slips.append(slip)

    return unique_slips[: config.MAX_SLIPS_RETURNED]


def _prop_decimal_odds(vp: ValuedProp) -> float:
    """Return the correct decimal odds for this prop based on its graded side."""
    side = vp.backing_data.get("side", "over")
    if side == "under" and vp.prop.under_odds_decimal and vp.prop.under_odds_decimal > 1.0:
        return vp.prop.under_odds_decimal
    return vp.prop.over_odds_decimal


def _estimate_leg_counts(eligible: list[ValuedProp], target_decimal: float) -> list[int]:
    """Estimate how many legs needed to reach target_decimal."""
    if not eligible:
        return [3]

    avg_odds = sum(_prop_decimal_odds(vp) for vp in eligible) / len(eligible)
    if avg_odds <= 1.0:
        return [3, 4]

    try:
        est = round(math.log(target_decimal) / math.log(avg_odds))
    except (ValueError, ZeroDivisionError):
        est = 3

    est = max(config.MIN_LEGS, min(config.MAX_LEGS, est))
    # Search ±1 around estimate
    return sorted({max(config.MIN_LEGS, est - 1), est, min(config.MAX_LEGS, est + 1)})


# Maps combo markets to the component markets they subsume.
# A slip cannot contain a combo market AND any of its components for the same player.
_MARKET_COMPONENTS: dict[str, set[str]] = {
    "player_points_rebounds_assists": {"player_points", "player_rebounds", "player_assists"},
    "player_points_rebounds": {"player_points", "player_rebounds"},
    "player_points_assists": {"player_points", "player_assists"},
    "player_rebounds_assists": {"player_rebounds", "player_assists"},
}


def _has_overlapping_markets(combo: tuple[ValuedProp, ...]) -> bool:
    """
    Return True if any player appears with both a combo market and one of its component markets.
    e.g. Player X has PRA + PTS → invalid (PTS is a component of PRA).
    """
    # Group markets by player
    player_markets: dict[str, set[str]] = {}
    for vp in combo:
        name = vp.prop.player_name
        market = vp.prop.market
        player_markets.setdefault(name, set()).add(market)

    for name, markets in player_markets.items():
        for combo_market, components in _MARKET_COMPONENTS.items():
            if combo_market in markets and markets & components:
                return True
    return False


def _search_combinations(
    eligible: list[ValuedProp],
    target_decimal: float,
    n: int,
) -> list[BetSlip]:
    """Generate all N-leg combinations and score them."""
    tolerance = config.ODDS_TOLERANCE
    results: list[tuple[float, BetSlip]] = []

    for combo in combinations(eligible, n):
        # Constraint: max 2 props per player (but not OVER+UNDER same market)
        player_counts: dict[str, int] = {}
        player_market_sides: dict[tuple, set] = {}
        skip = False
        for vp in combo:
            name = vp.prop.player_name
            player_counts[name] = player_counts.get(name, 0) + 1
            # Track (player, market) → set of sides; reject if same player has OVER+UNDER same market
            key = (name, vp.prop.market)
            sides = player_market_sides.setdefault(key, set())
            sides.add(vp.backing_data.get("side", "over"))
            if len(sides) > 1:  # both over and under on same market for same player
                skip = True
                break
        if skip or any(c > 2 for c in player_counts.values()):
            continue

        # Constraint: no combo market + component market for the same player
        if _has_overlapping_markets(combo):
            continue

        combined_odds = 1.0
        for vp in combo:
            combined_odds *= _prop_decimal_odds(vp)

        # Odds proximity filter
        proximity = abs(combined_odds - target_decimal) / target_decimal
        if proximity > tolerance:
            continue

        slip = _make_slip(list(combo), combined_odds, target_decimal)
        slip_score = _score_slip(slip, proximity)
        results.append((slip_score, slip))

    results.sort(key=lambda x: x[0], reverse=True)
    return [slip for _, slip in results[: config.MAX_SLIPS_RETURNED * 2]]


def _make_slip(
    combo: list[ValuedProp],
    combined_odds: float,
    target_decimal: float,
) -> BetSlip:
    legs = [
        BetLeg(
            valued_prop=vp,
            side=vp.backing_data.get("side", "over"),
            decimal_odds=_prop_decimal_odds(vp),
        )
        for vp in combo
    ]

    avg_score = sum(vp.value_score for vp in combo) / len(combo)
    has_correlated = _has_correlated_legs(legs)

    summary = _build_summary(legs, combined_odds)

    return BetSlip(
        legs=legs,
        combined_decimal_odds=round(combined_odds, 3),
        target_decimal_odds=target_decimal,
        total_value_score=round(avg_score, 1),
        summary=summary,
        has_correlated_legs=has_correlated,
    )


def _score_slip(slip: BetSlip, odds_proximity: float) -> float:
    """
    slip_score = avg_value * 0.5 + odds_proximity_score * 0.3 + independence * 0.2
    """
    avg_value = slip.total_value_score / 100

    # proximity_score: 1.0 = exact match, 0.0 = at tolerance boundary
    proximity_score = max(0.0, 1.0 - odds_proximity / config.ODDS_TOLERANCE)

    independence = 0.8 if slip.has_correlated_legs else 1.0

    return avg_value * 0.5 + proximity_score * 0.3 + independence * 0.2


def _has_correlated_legs(legs: list[BetLeg]) -> bool:
    """True if 2+ legs are from the same game."""
    game_ids = [leg.valued_prop.prop.game.game_id for leg in legs]
    return len(game_ids) != len(set(game_ids))


def _build_summary(legs: list[BetLeg], combined_odds: float) -> str:
    parts = []
    for leg in legs:
        vp = leg.valued_prop
        market_label = config.MARKET_MAP.get(vp.prop.market, {}).get("label", vp.prop.market)
        bookie = "[PP]" if vp.prop.is_paddy_power else f"[{vp.prop.bookmaker}]"
        direction = leg.side.upper()  # "OVER" or "UNDER"
        parts.append(
            f"{vp.prop.player_name} {direction} {vp.prop.line} {market_label} "
            f"@{leg.decimal_odds:.2f} {bookie}"
        )
    return " | ".join(parts) + f" → {combined_odds:.2f}"
