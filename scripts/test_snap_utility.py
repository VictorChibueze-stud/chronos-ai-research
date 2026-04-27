from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.override_utils import assign_boundary_roles, snap_to_wick_extreme


@dataclass
class Candle:
    timestamp: datetime
    high: float
    low: float


def _make_candles() -> list[Candle]:
    base = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    highs = [100, 102, 104, 106, 109, 111, 108, 105, 103]
    lows = [95, 93, 90, 88, 86, 84, 87, 89, 91]
    return [
        Candle(timestamp=base + timedelta(minutes=15 * i), high=float(highs[i]), low=float(lows[i]))
        for i in range(len(highs))
    ]


def _print_result(name: str, passed: bool) -> bool:
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return passed


def test_downtrend_impulse_end() -> bool:
    candles = _make_candles()
    approx_ts = candles[4].timestamp
    result = snap_to_wick_extreme(
        approx_price=85.0,
        approx_timestamp=approx_ts,
        candles=candles,
        trend_direction="down",
        boundary_role="impulse_end",
        search_radius=2,
    )
    return bool(
        result
        and result["snapped_price"] == 84.0
        and result["snapped_timestamp"] == candles[5].timestamp
        and result["candle_index"] == 5
    )


def test_downtrend_retracement_end() -> bool:
    candles = _make_candles()
    approx_ts = candles[4].timestamp
    result = snap_to_wick_extreme(
        approx_price=110.0,
        approx_timestamp=approx_ts,
        candles=candles,
        trend_direction="down",
        boundary_role="retracement_end",
        search_radius=2,
    )
    return bool(
        result
        and result["snapped_price"] == 111.0
        and result["snapped_timestamp"] == candles[5].timestamp
        and result["candle_index"] == 5
    )


def test_uptrend_impulse_end() -> bool:
    candles = _make_candles()
    approx_ts = candles[4].timestamp
    result = snap_to_wick_extreme(
        approx_price=110.0,
        approx_timestamp=approx_ts,
        candles=candles,
        trend_direction="up",
        boundary_role="impulse_end",
        search_radius=2,
    )
    return bool(
        result
        and result["snapped_price"] == 111.0
        and result["snapped_timestamp"] == candles[5].timestamp
        and result["candle_index"] == 5
    )


def test_uptrend_retracement_end() -> bool:
    candles = _make_candles()
    approx_ts = candles[4].timestamp
    result = snap_to_wick_extreme(
        approx_price=85.0,
        approx_timestamp=approx_ts,
        candles=candles,
        trend_direction="up",
        boundary_role="retracement_end",
        search_radius=2,
    )
    return bool(
        result
        and result["snapped_price"] == 84.0
        and result["snapped_timestamp"] == candles[5].timestamp
        and result["candle_index"] == 5
    )


def test_assign_roles_downtrend() -> bool:
    r1 = assign_boundary_roles(35, 45, "down")
    r2 = assign_boundary_roles(45, 35, "down")
    return (
        r1["impulse_end_price"] == 35.0
        and r1["retracement_end_price"] == 45.0
        and r2["impulse_end_price"] == 35.0
        and r2["retracement_end_price"] == 45.0
    )


def test_assign_roles_uptrend() -> bool:
    r1 = assign_boundary_roles(75, 85, "up")
    r2 = assign_boundary_roles(85, 75, "up")
    return (
        r1["impulse_end_price"] == 85.0
        and r1["retracement_end_price"] == 75.0
        and r2["impulse_end_price"] == 85.0
        and r2["retracement_end_price"] == 75.0
    )


def main() -> None:
    results = [
        _print_result("1) Downtrend impulse_end snap", test_downtrend_impulse_end()),
        _print_result("2) Downtrend retracement_end snap", test_downtrend_retracement_end()),
        _print_result("3) Uptrend impulse_end snap", test_uptrend_impulse_end()),
        _print_result("4) Uptrend retracement_end snap", test_uptrend_retracement_end()),
        _print_result("5) assign_boundary_roles downtrend", test_assign_roles_downtrend()),
        _print_result("6) assign_boundary_roles uptrend", test_assign_roles_uptrend()),
    ]

    passed = sum(1 for r in results if r)
    print(f"\nSummary: {passed}/6 passed")


if __name__ == "__main__":
    main()
