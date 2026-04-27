from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.override_resolver import (  # noqa: E402
    resolve_global_override,
    resolve_walker_depth_override,
)


@dataclass
class Candle:
    timestamp: datetime
    high: float
    low: float


@dataclass
class Override:
    approx_price_a: float
    approx_timestamp_a: datetime
    approx_price_b: float
    approx_timestamp_b: datetime
    search_radius: int = 10
    depth_index: int | None = None


def _print_result(name: str, passed: bool) -> bool:
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return passed


def _make_downtrend_candles() -> list[Candle]:
    base = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    highs = [120, 112, 104, 96, 80, 40, 45, 41, 38, 36, 35, 34]
    lows = [110, 101, 92, 82, 60, 35, 38, 36, 33, 31, 30, 32]
    return [
        Candle(timestamp=base + timedelta(hours=i), high=float(highs[i]), low=float(lows[i]))
        for i in range(len(highs))
    ]


def _make_uptrend_candles() -> list[Candle]:
    base = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
    highs = [35, 42, 55, 68, 76, 85, 83, 88, 95, 108, 120, 118]
    lows = [30, 33, 39, 49, 76, 75, 77, 80, 84, 96, 105, 110]
    return [
        Candle(timestamp=base + timedelta(hours=i), high=float(highs[i]), low=float(lows[i]))
        for i in range(len(highs))
    ]


def test_global_downtrend() -> bool:
    candles = _make_downtrend_candles()
    override = Override(
        approx_price_a=35.2,
        approx_timestamp_a=candles[5].timestamp,
        approx_price_b=44.6,
        approx_timestamp_b=candles[6].timestamp,
        search_radius=1,
    )

    result = resolve_global_override(override, candles, "down")
    if not result:
        return False

    trend_result = result["trend_result"]
    legs = trend_result["legs"]
    if len(legs) != 3:
        return False

    return (
        trend_result["trend"] == "down"
        and legs[0]["type"] == "impulse"
        and legs[0]["start_price"] == 120.0
        and legs[0]["end_price"] == 35.0
        and legs[1]["type"] == "retracement"
        and legs[1]["start_price"] == 35.0
        and legs[1]["end_price"] == 45.0
        and legs[2]["type"] == "impulse"
        and legs[2]["start_price"] == 45.0
    )


def test_global_uptrend() -> bool:
    candles = _make_uptrend_candles()
    override = Override(
        approx_price_a=74.8,
        approx_timestamp_a=candles[5].timestamp,
        approx_price_b=84.9,
        approx_timestamp_b=candles[5].timestamp,
        search_radius=1,
    )

    result = resolve_global_override(override, candles, "up")
    if not result:
        return False

    trend_result = result["trend_result"]
    legs = trend_result["legs"]
    if len(legs) != 3:
        return False

    return (
        trend_result["trend"] == "up"
        and legs[0]["type"] == "impulse"
        and legs[0]["start_price"] == 30.0
        and legs[0]["end_price"] == 85.0
        and legs[1]["type"] == "retracement"
        and legs[1]["start_price"] == 85.0
        and legs[1]["end_price"] == 75.0
        and legs[2]["type"] == "impulse"
        and legs[2]["start_price"] == 75.0
    )


def test_walker_depth_override() -> bool:
    candles = _make_uptrend_candles()
    override = Override(
        approx_price_a=74.8,
        approx_timestamp_a=candles[5].timestamp,
        approx_price_b=84.9,
        approx_timestamp_b=candles[5].timestamp,
        search_radius=1,
        depth_index=2,
    )

    zone = resolve_walker_depth_override(override, candles, depth_index=2, trend_direction="up")
    if not zone:
        return False

    return (
        zone["lower_boundary"] == 75.0
        and zone["upper_boundary"] == 85.0
        and zone["trend_direction"] == "up"
        and zone["depth_index"] == 2
    )


def main() -> None:
    results = [
        _print_result("1) Global resolver downtrend", test_global_downtrend()),
        _print_result("2) Global resolver uptrend", test_global_uptrend()),
        _print_result("3) Walker depth resolver", test_walker_depth_override()),
    ]

    passed = sum(1 for r in results if r)
    print(f"\nSummary: {passed}/3 passed")


if __name__ == "__main__":
    main()
