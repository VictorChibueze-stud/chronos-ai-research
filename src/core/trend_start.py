"""
Standalone trend start detector.
Uses absolute window high/low and recency to pick trend direction.
Used for visual testing only — does not affect the existing pipeline.
"""

from __future__ import annotations

from typing import Any


def find_trend_start(
    candles: list,
    min_move_pct: float = 0.03,
) -> dict[str, Any] | None:
    """
    Find the true start of the current trend.

    Logic:
    1. Find the absolute highest high in the window and its date.
    2. Find the absolute lowest low in the window and its date.
    3. Whichever is more recent defines the trend direction and is the trend start.
       - Most recent is a HIGH → downtrend from that high
       - Most recent is a LOW → uptrend from that low
    4. Validate minimum move from trend start to current price.

    No scoring. No window parameters. Just two extremes and their dates.
    """
    if len(candles) < 10:
        return None

    current_price = float(candles[-1].close)

    # Find absolute highest high and its candle
    highest_candle = max(candles, key=lambda c: float(c.high))
    highest_price = float(highest_candle.high)
    highest_index = next(i for i, c in enumerate(candles) if c is highest_candle)

    # Find absolute lowest low and its candle
    lowest_candle = min(candles, key=lambda c: float(c.low))
    lowest_price = float(lowest_candle.low)
    lowest_index = next(i for i, c in enumerate(candles) if c is lowest_candle)

    # Whichever extreme is more recent defines the trend
    if highest_index > lowest_index:
        # High came after the low — price rose to that high and has been falling since
        trend = "down"
        anchor_price = highest_price
        anchor_candle = highest_candle
        anchor_index = highest_index
    else:
        # Low came after the high — price fell to that low and has been rising since
        trend = "up"
        anchor_price = lowest_price
        anchor_candle = lowest_candle
        anchor_index = lowest_index

    # Validate minimum move from anchor to current price
    move_pct = abs(anchor_price - current_price) / anchor_price
    if move_pct < min_move_pct:
        return None

    return {
        "trend": trend,
        "start_price": anchor_price,
        "start_timestamp": anchor_candle.timestamp,
        "start_index": anchor_index,
        "current_price": current_price,
        "current_timestamp": candles[-1].timestamp,
        "move_pct": round(move_pct * 100, 2),
    }
