"""Leg metrics computation for trend analysis.

Pure, stateless module for computing normalised metrics on individual legs
(impulses and retracements) extracted by identify_trend.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SECONDS_PER_CANDLE = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def _seconds_to_human(seconds: int) -> str:
    """Convert seconds to human-readable duration string."""
    days = seconds // 86400
    remainder = seconds % 86400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "0m"


# Computes normalised metrics for a single leg (impulse or retracement).
# price_move_pct is the primary normalised metric — comparable across assets and timeframes.
# velocity_pct_per_candle measures speed: high = steep fast move, low = slow grinding move.
# is_synthetic=True means absolute prices are meaningless — use only percentage fields.
# duration_human is for agent-readable output and logging.
def compute_leg_metrics(
    leg: Dict[str, Any],
    candles: List[Any],
    interval: str,
    is_synthetic: bool = False,
) -> Optional[Dict[str, Any]]:
    """Compute normalised metrics for a single leg.

    Args:
        leg: Leg dict from identify_trend with start_price, start_index, end_price, end_index
        candles: Full candle list used in trend identification
        interval: Timeframe string (e.g. "1h", "4h", "1d")
        is_synthetic: If True, indicates absolute prices are meaningless

    Returns:
        Dict with metrics or None if insufficient data (missing start_price or start_index)
    """
    start_price = leg.get("start_price")
    start_index = leg.get("start_index")
    end_price = leg.get("end_price")
    end_index = leg.get("end_index")

    if start_price is None or start_index is None:
        return None

    start_price = float(start_price)

    # Compute price metrics
    price_move_abs = None
    price_move_pct = None
    direction_pct = None

    if end_price is not None:
        end_price = float(end_price)
        price_move_abs = abs(end_price - start_price)
        if start_price != 0:
            price_move_pct = round((price_move_abs / start_price) * 100, 2)
            # Signed version: negative for downward, positive for upward
            direction_pct = round(((end_price - start_price) / start_price) * 100, 2)

    # Compute duration metrics
    if end_index is not None:
        duration_candles = end_index - start_index
    else:
        duration_candles = len(candles) - 1 - start_index

    duration_seconds = None
    duration_human = None
    if interval in SECONDS_PER_CANDLE:
        duration_seconds = duration_candles * SECONDS_PER_CANDLE[interval]
        duration_human = _seconds_to_human(duration_seconds)

    # Compute velocity
    velocity_pct_per_candle = None
    if price_move_pct is not None and duration_candles > 0:
        velocity_pct_per_candle = round(price_move_pct / duration_candles, 4)

    return {
        "price_move_abs": price_move_abs,
        "price_move_pct": price_move_pct,
        "direction_pct": direction_pct,
        "duration_candles": duration_candles,
        "duration_seconds": duration_seconds,
        "duration_human": duration_human,
        "velocity_pct_per_candle": velocity_pct_per_candle,
        "is_synthetic": is_synthetic,
        "is_open": end_price is None,
    }


# Call this after identify_trend and compute_internal_structure.
# Applies to global legs and internal legs recursively.
# interval must match the timeframe used to fetch candles e.g. "1h", "4h".
def annotate_legs_with_metrics(
    legs: List[Dict[str, Any]],
    candles: List[Any],
    interval: str,
    is_synthetic: bool = False,
) -> List[Dict[str, Any]]:
    """Annotate all legs with computed metrics, including internal structure legs.

    Mutates legs in place and returns them.

    Args:
        legs: List of leg dicts from identify_trend
        candles: Full candle list used in trend identification
        interval: Timeframe string (e.g. "1h", "4h", "1d")
        is_synthetic: If True, indicates absolute prices are meaningless

    Returns:
        The mutated legs list
    """
    for leg in legs:
        leg["metrics"] = compute_leg_metrics(leg, candles, interval, is_synthetic)

        # Recursively annotate internal structure legs
        if leg.get("internal_structure") is not None:
            internal = leg["internal_structure"]
            if "legs" in internal:
                annotate_legs_with_metrics(
                    internal["legs"],
                    candles[leg["start_index"] : leg["end_index"] + 1]
                    if leg.get("end_index") is not None
                    else candles,
                    interval,
                    is_synthetic,
                )

    return legs


# Aggregates leg metrics across a trend to answer questions like:
# "What is the average impulse size in this trend?"
# "Is momentum accelerating or decelerating across successive impulses?"
# "How long do retracements typically last?"
# Use velocity_trend as an early exhaustion signal.
def summarise_leg_metrics(
    legs: List[Dict[str, Any]], leg_type: str = "impulse"
) -> Optional[Dict[str, Any]]:
    """Compute summary statistics across matching legs.

    Args:
        legs: List of leg dicts with metrics
        leg_type: Filter to "impulse" or "retracement"

    Returns:
        Summary dict with count, mean/min/max stats, velocity_trend, or None if no matching legs
    """
    matching_legs = [
        leg
        for leg in legs
        if leg.get("type") == leg_type
        and leg.get("confirmed") is True
        and leg.get("metrics") is not None
    ]

    if not matching_legs:
        return None

    metrics_list = [leg["metrics"] for leg in matching_legs]

    # Filter out None values for each metric
    price_moves = [
        m["price_move_pct"]
        for m in metrics_list
        if m.get("price_move_pct") is not None
    ]
    durations = [
        m["duration_candles"] for m in metrics_list if m.get("duration_candles") is not None
    ]
    velocities = [
        m["velocity_pct_per_candle"]
        for m in metrics_list
        if m.get("velocity_pct_per_candle") is not None
    ]

    # Compute velocity trend
    velocity_trend = "mixed"
    if len(velocities) >= 2:
        all_accelerating = all(
            velocities[i] < velocities[i + 1] for i in range(len(velocities) - 1)
        )
        all_decelerating = all(
            velocities[i] > velocities[i + 1] for i in range(len(velocities) - 1)
        )
        if all_accelerating:
            velocity_trend = "accelerating"
        elif all_decelerating:
            velocity_trend = "decelerating"

    return {
        "count": len(matching_legs),
        "mean_price_move_pct": round(sum(price_moves) / len(price_moves), 2)
        if price_moves
        else None,
        "min_price_move_pct": min(price_moves) if price_moves else None,
        "max_price_move_pct": max(price_moves) if price_moves else None,
        "mean_duration_candles": round(sum(durations) / len(durations), 1) if durations else None,
        "min_duration_candles": min(durations) if durations else None,
        "max_duration_candles": max(durations) if durations else None,
        "mean_velocity_pct_per_candle": round(sum(velocities) / len(velocities), 4)
        if velocities
        else None,
        "velocity_trend": velocity_trend,
        "total_price_move_pct": round(sum(price_moves), 2) if price_moves else None,
    }
