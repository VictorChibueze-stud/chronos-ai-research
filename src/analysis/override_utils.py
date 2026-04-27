from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _candle_field(candle: Any, field_name: str) -> Any:
    if isinstance(candle, dict):
        return candle.get(field_name)
    return getattr(candle, field_name, None)


def assign_boundary_roles(
    price_a: float,
    price_b: float,
    trend_direction: str,
) -> dict:
    """Normalize two boundary prices into impulse/retracement role prices."""
    trend = trend_direction.lower().strip()
    if trend not in {"up", "down"}:
        raise ValueError("trend_direction must be 'up' or 'down'")

    low_price = min(float(price_a), float(price_b))
    high_price = max(float(price_a), float(price_b))

    if trend == "down":
        return {
            "impulse_end_price": low_price,
            "retracement_end_price": high_price,
        }

    return {
        "impulse_end_price": high_price,
        "retracement_end_price": low_price,
    }


def snap_to_wick_extreme(
    approx_price: float,
    approx_timestamp: datetime,
    candles: list,
    trend_direction: str,
    boundary_role: str,
    search_radius: int = 10,
) -> dict | None:
    """Snap an approximate boundary to the true wick extreme near the target time.

    The function searches within +/- search_radius candles around the candle nearest
    to approx_timestamp and returns the wick extreme determined by trend_direction
    and boundary_role.
    """
    if not candles:
        return None

    trend = trend_direction.lower().strip()
    role = boundary_role.lower().strip()
    if trend not in {"up", "down"}:
        raise ValueError("trend_direction must be 'up' or 'down'")
    if role not in {"impulse_end", "retracement_end"}:
        raise ValueError("boundary_role must be 'impulse_end' or 'retracement_end'")
    if search_radius < 0:
        raise ValueError("search_radius must be >= 0")

    target_ts = _ensure_utc(approx_timestamp)

    indexed = []
    for idx, candle in enumerate(candles):
        ts = _candle_field(candle, "timestamp")
        high = _candle_field(candle, "high")
        low = _candle_field(candle, "low")
        if ts is None or high is None or low is None:
            continue
        indexed.append((idx, candle, _ensure_utc(ts)))

    if not indexed:
        return None

    nearest_index, _, _ = min(
        indexed,
        key=lambda item: abs((item[2] - target_ts).total_seconds()),
    )

    window_start = max(0, nearest_index - search_radius)
    window_end = min(len(candles) - 1, nearest_index + search_radius)

    window = []
    for idx in range(window_start, window_end + 1):
        candle = candles[idx]
        ts = _candle_field(candle, "timestamp")
        high = _candle_field(candle, "high")
        low = _candle_field(candle, "low")
        if ts is None or high is None or low is None:
            continue
        window.append(
            {
                "index": idx,
                "timestamp": _ensure_utc(ts),
                "high": float(high),
                "low": float(low),
            }
        )

    if not window:
        return None

    use_low = (
        (trend == "down" and role == "impulse_end")
        or (trend == "up" and role == "retracement_end")
    )

    if use_low:
        extreme_price = min(c["low"] for c in window)
        candidates = [c for c in window if c["low"] == extreme_price]
    else:
        extreme_price = max(c["high"] for c in window)
        candidates = [c for c in window if c["high"] == extreme_price]

    best = min(
        candidates,
        key=lambda c: (
            abs((c["timestamp"] - target_ts).total_seconds()),
            abs((extreme_price - float(approx_price))),
            c["index"],
        ),
    )

    return {
        "snapped_price": extreme_price,
        "snapped_timestamp": best["timestamp"],
        "candle_index": best["index"],
    }
