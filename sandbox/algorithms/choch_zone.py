"""CHoCH (Change of Character) zone computation for Ikenga.

Pure, stateless module. No side effects. No file I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Computes the CHoCH zone for the most recent confirmed impulse in a trend.
#
# The CHoCH zone is a PRICE RANGE, not a line. It represents the area of ambiguity
# around where the market "decided" to reverse direction.
#
# Zone definition:
#   lower_boundary = start_price of the most recent confirmed impulse leg
#   upper_boundary = the BOS level that the most recent confirmed impulse broke through
#                    (i.e. the end_price of the confirmed impulse leg immediately
#                     preceding the most recent confirmed impulse)
#
# In a downtrend: lower_boundary < upper_boundary (zone is a band below the prior BOS)
# In an uptrend:  upper_boundary > lower_boundary (zone is a band above the prior low)
#
# The zone is only computable when there are at least 2 confirmed impulse legs,
# because the upper boundary requires a prior impulse to exist.
# Returns None if fewer than 2 confirmed impulse legs exist.
def compute_choch_zone(
    legs: List[Dict[str, Any]],
    trend: str,
) -> Optional[Dict[str, Any]]:
    """Compute the CHoCH zone for the most recent confirmed impulse in a trend.

    Args:
        legs: List of leg dicts from identify_trend.
        trend: Trend direction — "up" or "down".

    Returns:
        Zone dict or None if fewer than 2 confirmed impulse legs exist.
    """
    confirmed_impulses = [
        leg
        for leg in legs
        if (
            leg.get("type") == "impulse"
            and leg.get("confirmed") is True
            and leg.get("end_price") is not None
        )
    ]
    if len(confirmed_impulses) < 2:
        return None

    most_recent = confirmed_impulses[-1]
    prior = confirmed_impulses[-2]

    most_recent_start = float(most_recent["start_price"])
    prior_end = float(prior["end_price"])

    lower_boundary = min(most_recent_start, prior_end)
    upper_boundary = max(most_recent_start, prior_end)

    zone_width_pct = (
        round((upper_boundary - lower_boundary) / lower_boundary * 100, 2)
        if lower_boundary != 0
        else 0.0
    )
    zone_midpoint = (upper_boundary + lower_boundary) / 2

    return {
        "lower_boundary": lower_boundary,
        "upper_boundary": upper_boundary,
        "zone_width_pct": zone_width_pct,
        "zone_midpoint": zone_midpoint,
        "trend_direction": trend,
        "source_impulse_start_index": int(most_recent["start_index"]),
        "source_impulse_end_index": int(most_recent["end_index"]),
        "prior_impulse_end_index": int(prior["end_index"]),
    }


# Measures where current_price sits relative to the CHoCH zone.
# proximity_pct:
#   0.0   = price is exactly at zone lower_boundary
#   100.0 = price is exactly at zone upper_boundary
#   < 0   = price is below the zone (not yet reached)
#   > 100 = price is above the zone (has passed through)
# price_in_zone: True if 0 <= proximity_pct <= 100
# price_above_zone: True if proximity_pct > 100
# price_below_zone: True if proximity_pct < 0
def compute_choch_proximity(
    choch_zone: Dict[str, Any],
    current_price: float,
) -> Dict[str, Any]:
    """Measure where current_price sits relative to the CHoCH zone.

    Args:
        choch_zone: Zone dict from compute_choch_zone.
        current_price: The price to evaluate (e.g. last candle close).

    Returns:
        Proximity dict with boolean flags and distance metrics.
    """
    lower = float(choch_zone["lower_boundary"])
    upper = float(choch_zone["upper_boundary"])
    midpoint = float(choch_zone["zone_midpoint"])
    zone_range = upper - lower
    current_price = float(current_price)

    if zone_range == 0:
        return {
            "current_price": current_price,
            "proximity_pct": 0.0,
            "price_in_zone": True,
            "price_above_zone": False,
            "price_below_zone": False,
            "distance_to_lower_boundary": abs(current_price - lower),
            "distance_to_upper_boundary": abs(current_price - upper),
            "distance_to_midpoint_pct": 0.0,
        }

    proximity_pct = round((current_price - lower) / zone_range * 100, 2)
    price_in_zone = 0.0 <= proximity_pct <= 100.0
    price_above_zone = proximity_pct > 100.0
    price_below_zone = proximity_pct < 0.0

    return {
        "current_price": current_price,
        "proximity_pct": proximity_pct,
        "price_in_zone": price_in_zone,
        "price_above_zone": price_above_zone,
        "price_below_zone": price_below_zone,
        "distance_to_lower_boundary": abs(current_price - lower),
        "distance_to_upper_boundary": abs(current_price - upper),
        "distance_to_midpoint_pct": round(
            abs(current_price - midpoint) / zone_range * 100, 2
        ),
    }


# Annotates each confirmed impulse leg with its CHoCH zone.
# Only the most recent confirmed impulse gets a zone by default,
# but this function annotates all confirmed impulse legs for historical analysis.
# Each confirmed impulse leg gets a "choch_zone" key.
# Legs with insufficient prior impulse context get choch_zone = None.
# Retracement legs and unconfirmed legs get choch_zone = None.
# Mutates legs in place and returns them.
def annotate_legs_with_choch_zones(
    legs: List[Dict[str, Any]],
    trend: str,
) -> List[Dict[str, Any]]:
    """Annotate all legs with their CHoCH zones for historical analysis.

    Args:
        legs: List of leg dicts from identify_trend.
        trend: Trend direction — "up" or "down".

    Returns:
        The mutated legs list.
    """
    seen_confirmed_impulses: List[Dict[str, Any]] = []

    for leg in legs:
        if leg.get("type") != "impulse" or leg.get("confirmed") is not True:
            leg["choch_zone"] = None
            continue

        if leg.get("end_price") is None:
            leg["choch_zone"] = None
            seen_confirmed_impulses.append(leg)
            continue

        if not seen_confirmed_impulses:
            leg["choch_zone"] = None
        else:
            prior = seen_confirmed_impulses[-1]
            most_recent_start = float(leg["start_price"])
            prior_end = float(prior["end_price"])

            lower_boundary = min(most_recent_start, prior_end)
            upper_boundary = max(most_recent_start, prior_end)
            zone_width_pct = (
                round((upper_boundary - lower_boundary) / lower_boundary * 100, 2)
                if lower_boundary != 0
                else 0.0
            )
            zone_midpoint = (upper_boundary + lower_boundary) / 2

            leg["choch_zone"] = {
                "lower_boundary": lower_boundary,
                "upper_boundary": upper_boundary,
                "zone_width_pct": zone_width_pct,
                "zone_midpoint": zone_midpoint,
                "trend_direction": trend,
                "source_impulse_start_index": int(leg["start_index"]),
                "source_impulse_end_index": int(leg["end_index"]),
                "prior_impulse_end_index": int(prior["end_index"]),
            }

        seen_confirmed_impulses.append(leg)

    return legs


# Returns the CHoCH zone relevant to the current market state.
# Uses the most recent confirmed impulse leg that has a computed choch_zone.
# Also computes proximity using the last candle's close price as current_price.
# Returns None if no zone is computable.
# This is the primary entry point for downstream analysis modules.
def get_active_choch_zone(
    legs: List[Dict[str, Any]],
    trend: str,
    candles: List[Any],
) -> Optional[Dict[str, Any]]:
    """Return the CHoCH zone relevant to the current market state.

    Args:
        legs: List of leg dicts from identify_trend.
        trend: Trend direction — "up" or "down".
        candles: Full candle list; last candle's close is used as current price.

    Returns:
        Dict with zone, proximity, source_leg_index, and current_price, or None.
    """
    annotate_legs_with_choch_zones(legs, trend)

    source_leg = None
    source_leg_index = None
    for i, leg in enumerate(legs):
        if leg.get("choch_zone") is not None:
            source_leg = leg
            source_leg_index = i

    if source_leg is None:
        return None

    current_price = float(candles[-1].close)
    choch_zone = source_leg["choch_zone"]
    proximity = compute_choch_proximity(choch_zone, current_price)

    return {
        "choch_zone": choch_zone,
        "proximity": proximity,
        "source_leg_index": source_leg_index,
        "current_price": current_price,
    }
