from datetime import datetime, timedelta, timezone

import pandas as pd

from src.core.features import Candle
from src.scanner.universe import compute_atr, compute_correlation_groups


def _make_candle(ts: datetime, o: float, h: float, l: float, c: float, v: float = 0.0) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _make_series(symbol: str, base: float, rng: float, volume: float, n: int = 20) -> list[Candle]:
    """Build deterministic candles with controllable average range and final volume."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[Candle] = []
    price = base
    for i in range(n):
        ts = start + timedelta(hours=i)
        high = price + rng
        low = price - rng
        close = price + (0.2 if i % 2 == 0 else -0.2)
        vol = volume if i == n - 1 else 0.0
        candles.append(_make_candle(ts, price, high, low, close, vol))
        price = close
    return candles


def _scan_df(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["symbol", "interval", "trend"])


def test_compute_atr_simple_average_true_range_math():
    """ATR should equal the simple average of true ranges over period."""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        _make_candle(t0, 10.0, 12.0, 8.0, 10.0, 1.0),  # TR = 4.0
        _make_candle(t0 + timedelta(hours=1), 10.0, 15.0, 10.0, 12.0, 1.0),  # TR = 5.0
        _make_candle(t0 + timedelta(hours=2), 12.0, 13.0, 11.0, 12.0, 1.0),  # TR = 2.0
    ]

    atr = compute_atr(candles, period=3)

    assert atr == (4.0 + 5.0 + 2.0) / 3.0


def test_compute_atr_returns_zero_if_not_enough_candles():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        _make_candle(t0, 10.0, 12.0, 8.0, 10.0, 1.0),
        _make_candle(t0 + timedelta(hours=1), 10.0, 11.0, 9.0, 10.0, 1.0),
    ]

    assert compute_atr(candles, period=14) == 0.0


def test_compute_correlation_groups_tiebreaker_a_volume_wins():
    """If correlated symbols exist, the one with the highest positive volume wins."""
    scan_results_df = _scan_df(
        [
            ("EURUSD", "1h", "up"),
            ("EURUSD", "4h", "up"),
            ("GBPUSD", "1h", "up"),
            ("GBPUSD", "4h", "up"),
            ("AUDUSD", "1h", "up"),
            ("AUDUSD", "4h", "up"),
            ("USDJPY", "1h", "down"),
            ("USDJPY", "4h", "up"),
        ]
    )

    symbol_candle_map = {
        "EURUSD": _make_series("EURUSD", base=1.10, rng=0.003, volume=100.0),
        "GBPUSD": _make_series("GBPUSD", base=1.25, rng=0.003, volume=500.0),
        "AUDUSD": _make_series("AUDUSD", base=0.75, rng=0.003, volume=250.0),
        "USDJPY": _make_series("USDJPY", base=150.0, rng=0.30, volume=10.0),
    }

    filtered = compute_correlation_groups(scan_results_df, symbol_candle_map)

    kept_symbols = set(filtered["symbol"].unique())
    assert kept_symbols == {"GBPUSD", "USDJPY"}


def test_compute_correlation_groups_tiebreaker_b_atr_wins_when_volume_missing_or_zero():
    """If volume is unavailable/zero, highest ATR should win within a correlated group."""
    scan_results_df = _scan_df(
        [
            ("EURUSD", "1h", "up"),
            ("EURUSD", "4h", "down"),
            ("GBPUSD", "1h", "up"),
            ("GBPUSD", "4h", "down"),
            ("AUDUSD", "1h", "up"),
            ("AUDUSD", "4h", "down"),
            ("BTCUSDT", "1h", "down"),
            ("BTCUSDT", "4h", "down"),
        ]
    )

    # Correlated trio: EURUSD/GBPUSD/AUDUSD all share (up, down) trend signature.
    # Volumes are all zero on the latest candle, so ATR must break the tie.
    symbol_candle_map = {
        "EURUSD": _make_series("EURUSD", base=1.10, rng=0.010, volume=0.0),  # highest ATR
        "GBPUSD": _make_series("GBPUSD", base=1.25, rng=0.004, volume=0.0),
        "AUDUSD": _make_series("AUDUSD", base=0.75, rng=0.003, volume=0.0),
        "BTCUSDT": _make_series("BTCUSDT", base=40000.0, rng=100.0, volume=0.0),
    }

    filtered = compute_correlation_groups(scan_results_df, symbol_candle_map)

    kept_symbols = set(filtered["symbol"].unique())
    assert kept_symbols == {"EURUSD", "BTCUSDT"}


def test_compute_correlation_groups_tiebreaker_c_alphabetical_when_volume_and_atr_tie():
    """If volume and ATR tie, winner should be chosen alphabetically."""
    scan_results_df = _scan_df(
        [
            ("EURUSD", "1h", "up"),
            ("EURUSD", "4h", "up"),
            ("AUDUSD", "1h", "up"),
            ("AUDUSD", "4h", "up"),
            ("XAUUSD", "1h", "down"),
            ("XAUUSD", "4h", "up"),
        ]
    )

    # Same ranges -> same ATR, and latest volume is 0 for both.
    identical_eur = _make_series("EURUSD", base=1.10, rng=0.005, volume=0.0)
    identical_aud = _make_series("AUDUSD", base=1.10, rng=0.005, volume=0.0)

    symbol_candle_map = {
        "EURUSD": identical_eur,
        "AUDUSD": identical_aud,
        "XAUUSD": _make_series("XAUUSD", base=2000.0, rng=5.0, volume=0.0),
    }

    filtered = compute_correlation_groups(scan_results_df, symbol_candle_map)

    kept_symbols = set(filtered["symbol"].unique())
    assert kept_symbols == {"AUDUSD", "XAUUSD"}
