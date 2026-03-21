"""
PIP-based trend identification — Perceptually Important Points algorithm.
Independent implementation parallel to trend_id.py for direct comparison.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any, Optional
import math


# PIP extraction: iteratively finds the N most structurally significant price points.
# n_pips controls resolution — more PIPs = more detail, fewer = smoother structure.
# dist_measure controls what "significant" means geometrically:
#   "vertical"      — fast, intuitive, slightly biased toward large price moves
#   "perpendicular" — most geometrically correct, scale-normalised
#   "euclidean"     — rewards points far from either anchor, good for sharp spikes
def extract_pips(
    candles: List[Any],
    n_pips: int,
    dist_measure: str = "perpendicular"
) -> List[Dict]:
    """
    Extract n_pips perceptually important points from a candle list.

    Args:
        candles: List of Candle objects with close, timestamp
        n_pips: Target number of PIPs (minimum 2)
        dist_measure: "vertical", "perpendicular", or "euclidean"

    Returns:
        List of dicts: {"index": int, "price": float, "timestamp": datetime}
        sorted by index, always includes endpoints.
    """
    if n_pips < 2:
        n_pips = 2

    if len(candles) < 2:
        return []

    if len(candles) == 2:
        return [
            {"index": 0, "price": candles[0].close, "timestamp": candles[0].timestamp},
            {"index": len(candles) - 1, "price": candles[-1].close, "timestamp": candles[-1].timestamp},
        ]

    # Seed with endpoints using close price
    pips = [
        {"index": 0, "price": candles[0].close, "timestamp": candles[0].timestamp},
        {"index": len(candles) - 1, "price": candles[-1].close, "timestamp": candles[-1].timestamp},
    ]

    # Precompute price range and index scale for perpendicular distance
    all_prices = [c.close for c in candles]
    price_min, price_max = min(all_prices), max(all_prices)
    price_range = price_max - price_min
    if price_range == 0:
        price_range = 1  # Avoid division by zero on flat prices

    # Iteratively add PIPs until we reach n_pips or no candidates exist
    while len(pips) < n_pips:
        best_candidate = None
        best_distance = -1
        best_pair_idx = -1

        # Scan all gaps between adjacent PIPs
        for pair_idx in range(len(pips) - 1):
            pip_a = pips[pair_idx]
            pip_b = pips[pair_idx + 1]

            # Scan all candle indices strictly between pip_a and pip_b
            for idx in range(pip_a["index"] + 1, pip_b["index"]):
                candle = candles[idx]
                dist = _compute_distance(
                    candle.close, idx, pip_a, pip_b, candles, dist_measure, price_range
                )

                if dist > best_distance:
                    best_distance = dist
                    best_candidate = {
                        "index": idx,
                        "price": candle.close,
                        "timestamp": candle.timestamp,
                    }
                    best_pair_idx = pair_idx

        # If no candidate found, stop early
        if best_candidate is None:
            break

        # Insert candidate at correct position in sorted list
        pips.insert(best_pair_idx + 1, best_candidate)

    return pips


def _compute_distance(
    price: float,
    index: int,
    pip_a: Dict,
    pip_b: Dict,
    candles: List[Any],
    dist_measure: str,
    price_range: float,
) -> float:
    """Compute distance from a candidate point to the line connecting two PIPs."""

    if dist_measure == "vertical":
        # Vertical distance: difference from linear interpolation
        interp_price = _linear_interpolate(
            pip_a["index"], pip_a["price"],
            pip_b["index"], pip_b["price"],
            index
        )
        return abs(price - interp_price)

    elif dist_measure == "perpendicular":
        # Perpendicular distance in normalized space
        # Normalize index to [0, 1]
        norm_len = len(candles)
        norm_x_a = pip_a["index"] / norm_len if norm_len > 0 else 0
        norm_x_b = pip_b["index"] / norm_len if norm_len > 0 else 0
        norm_x = index / norm_len if norm_len > 0 else 0

        # Normalize price to [0, 1]
        norm_y_a = (pip_a["price"] - min([c.close for c in candles])) / price_range if price_range > 0 else 0
        norm_y_b = (pip_b["price"] - min([c.close for c in candles])) / price_range if price_range > 0 else 0
        norm_y = (price - min([c.close for c in candles])) / price_range if price_range > 0 else 0

        # Line from (norm_x_a, norm_y_a) to (norm_x_b, norm_y_b)
        # Point is (norm_x, norm_y)
        dx = norm_x_b - norm_x_a
        dy = norm_y_b - norm_y_a

        if dx == 0 and dy == 0:
            # Identical points, return Euclidean distance
            return math.sqrt((norm_x - norm_x_a) ** 2 + (norm_y - norm_y_a) ** 2)

        # Perpendicular distance = |ax + by + c| / sqrt(a^2 + b^2)
        # Line equation: dy * (x - x_a) - dx * (y - y_a) = 0
        numerator = abs(dy * (norm_x - norm_x_a) - dx * (norm_y - norm_y_a))
        denominator = math.sqrt(dx ** 2 + dy ** 2)

        return numerator / denominator if denominator > 0 else 0

    elif dist_measure == "euclidean":
        # Euclidean distance to nearest endpoint (in normalized space)
        norm_len = len(candles)
        norm_x = index / norm_len if norm_len > 0 else 0

        norm_y_min = min([c.close for c in candles])
        norm_y = (price - norm_y_min) / price_range if price_range > 0 else 0

        # Distance to pip_a
        norm_x_a = pip_a["index"] / norm_len if norm_len > 0 else 0
        norm_y_a = (pip_a["price"] - norm_y_min) / price_range if price_range > 0 else 0
        dist_a = math.sqrt((norm_x - norm_x_a) ** 2 + (norm_y - norm_y_a) ** 2)

        # Distance to pip_b
        norm_x_b = pip_b["index"] / norm_len if norm_len > 0 else 0
        norm_y_b = (pip_b["price"] - norm_y_min) / price_range if price_range > 0 else 0
        dist_b = math.sqrt((norm_x - norm_x_b) ** 2 + (norm_y - norm_y_b) ** 2)

        return min(dist_a, dist_b)

    else:
        raise ValueError(f"Unknown dist_measure: {dist_measure}")


def _linear_interpolate(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """Linear interpolation between two points."""
    if x2 == x1:
        return (y1 + y2) / 2
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def classify_pip_legs(pips: List[Dict]) -> Dict[str, Any]:
    """
    Convert PIPs into alternating impulse/retracement legs.

    Args:
        pips: Output from extract_pips, sorted by index

    Returns:
        Dict with keys:
        - "trend": "up" | "down" | "range"
        - "pips": the input pips list
        - "legs": List of leg dicts with type, indices, prices, timestamps, confirmed, slope
        - "current_phase": "impulse" | "retracement" | "unknown"
    """
    if len(pips) < 2:
        return {
            "trend": "range",
            "pips": pips,
            "legs": [],
            "current_phase": "unknown",
        }

    # Build legs from consecutive pairs
    legs = []
    for i in range(len(pips) - 1):
        pip_a = pips[i]
        pip_b = pips[i + 1]

        leg = {
            "type": None,  # Will be filled after trend determination
            "start_index": pip_a["index"],
            "start_price": pip_a["price"],
            "start_timestamp": pip_a["timestamp"],
            "end_index": pip_b["index"],
            "end_price": pip_b["price"],
            "end_timestamp": pip_b["timestamp"],
            "confirmed": True,
            "slope": (pip_b["price"] - pip_a["price"]) / (pip_b["index"] - pip_a["index"]),
        }
        legs.append(leg)

    # Determine trend: find largest single move (up vs down)
    if not legs:
        return {
            "trend": "range",
            "pips": pips,
            "legs": [],
            "current_phase": "unknown",
        }

    max_up_move = 0
    max_down_move = 0

    for leg in legs:
        move = leg["end_price"] - leg["start_price"]
        if move > 0:
            max_up_move = max(max_up_move, move)
        else:
            max_down_move = max(max_down_move, -move)

    # Determine trend based on largest single move
    total_move = max_up_move + max_down_move
    if total_move == 0:
        trend = "range"
    else:
        # If ratio of smaller to larger is within 20%, it's a range
        ratio = min(max_up_move, max_down_move) / max(max_up_move, max_down_move)
        if ratio >= 0.8:  # within 20%
            trend = "range"
        elif max_down_move > max_up_move:
            trend = "down"
        else:
            trend = "up"

    # Label legs as impulse/retracement based on trend
    for leg in legs:
        leg_direction = "up" if leg["end_price"] > leg["start_price"] else "down"

        if trend == "up":
            leg["type"] = "impulse" if leg_direction == "up" else "retracement"
        elif trend == "down":
            leg["type"] = "impulse" if leg_direction == "down" else "retracement"
        else:  # range
            leg["type"] = "impulse" if leg_direction == "up" else "retracement"

    current_phase = legs[-1]["type"] if legs else "unknown"

    return {
        "trend": trend,
        "pips": pips,
        "legs": legs,
        "current_phase": current_phase,
    }


def compute_pip_internal_structure(
    candles: List[Any],
    legs: List[Dict],
    n_pips: int,
    dist_measure: str = "perpendicular",
    n_pips_internal: Optional[int] = None,
) -> List[Dict]:
    """
    Add internal structure to confirmed impulse legs.

    Mutates legs in-place, adding "internal_structure" key to each leg.
    Internal structure indices are relative to the parent impulse slice.

    Args:
        candles: Full candle list
        legs: Legs from classify_pip_legs
        n_pips: PIP count for global structure (used to infer internal if not specified)
        dist_measure: "vertical" | "perpendicular" | "euclidean"
        n_pips_internal: PIPs for internal structure. Defaults to max(5, n_pips // 2).

    Returns:
        The mutated legs list
    """
    if n_pips_internal is None:
        n_pips_internal = max(5, n_pips // 2)

    for leg in legs:
        # Only process confirmed impulse legs
        if leg["type"] != "impulse" or not leg["confirmed"] or leg["end_index"] is None:
            leg["internal_structure"] = None
            continue

        start_idx = leg["start_index"]
        end_idx = leg["end_index"]
        slice_candles = candles[start_idx : end_idx + 1]

        # Slice too short for internal structure
        if len(slice_candles) < n_pips_internal + 2:
            leg["internal_structure"] = None
            continue

        # Extract and classify internal PIPs
        internal_pips = extract_pips(slice_candles, n_pips_internal, dist_measure)
        internal_result = classify_pip_legs(internal_pips)

        # Only store if not a range
        if internal_result["trend"] == "range":
            leg["internal_structure"] = None
        else:
            leg["internal_structure"] = internal_result

    return legs


# Top-level PIP trend identifier. Drop-in comparable with identify_trend() in trend_id.py.
# n_pips: number of PIPs for global structure. More = finer detail. Start with 9-13.
# dist_measure: "vertical" | "perpendicular" | "euclidean". Start with "perpendicular".
# n_pips_internal: PIPs used inside each impulse leg. Defaults to half of n_pips.
def identify_trend_pip(
    candles: List[Any],
    n_pips: int = 11,
    dist_measure: str = "perpendicular",
    n_pips_internal: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Identify trend using PIP algorithm. Drop-in comparable with identify_trend().

    Args:
        candles: List of Candle objects
        n_pips: Number of perceptually important points (default 11)
        dist_measure: "vertical" | "perpendicular" | "euclidean" (default "perpendicular")
        n_pips_internal: PIPs for internal structure (default half of n_pips)

    Returns:
        Dict with keys: "trend", "trend_start", "legs", "current_phase"
        Matches the schema of identify_trend() in trend_id.py
    """
    if n_pips_internal is None:
        n_pips_internal = max(5, n_pips // 2)

    # Edge case: too few candles
    if len(candles) < 2:
        return {
            "trend": "range",
            "trend_start": None,
            "legs": [],
            "current_phase": "unknown",
        }

    # Extract and classify PIPs
    pips = extract_pips(candles, n_pips, dist_measure)
    result = classify_pip_legs(pips)

    # Add internal structure to impulse legs
    compute_pip_internal_structure(candles, result["legs"], n_pips, dist_measure, n_pips_internal)

    # Build trend_start from first PIP
    trend_start = None
    if pips:
        trend_start = {
            "price": pips[0]["price"],
            "index": pips[0]["index"],
            "timestamp": pips[0]["timestamp"],
        }

    return {
        "trend": result["trend"],
        "trend_start": trend_start,
        "legs": result["legs"],
        "current_phase": result["current_phase"],
    }
