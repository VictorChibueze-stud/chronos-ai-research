"""Universe filtering helpers for scanner post-processing.

This module provides:
- ATR computation from deterministic Candle lists
- Correlation-group winner selection using the project tie-breaker hierarchy
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

import pandas as pd

from src.core.features import Candle


def compute_atr(candles: Sequence[Candle], period: int = 14) -> float:
    """Compute simple-average ATR for the trailing ``period`` candles.

    True Range (TR) per candle is:
    max(high - low, abs(high - prev_close), abs(low - prev_close))

    For the first candle, ``prev_close`` is unavailable so TR is ``high - low``.
    Returns ``0.0`` when there are not enough candles.
    """
    if period <= 0:
        return 0.0
    if len(candles) < period:
        return 0.0

    tr_values: List[float] = []
    prev_close = None

    for candle in candles:
        high_low = float(candle.high) - float(candle.low)
        if prev_close is None:
            tr = high_low
        else:
            tr = max(
                high_low,
                abs(float(candle.high) - prev_close),
                abs(float(candle.low) - prev_close),
            )
        tr_values.append(tr)
        prev_close = float(candle.close)

    window = tr_values[-period:]
    return float(sum(window) / period)


def _latest_positive_volume(candles: Sequence[Candle]) -> float:
    if not candles:
        return 0.0
    latest = candles[-1]
    volume = getattr(latest, "volume", 0.0)
    if volume is None:
        return 0.0
    return float(volume) if float(volume) > 0.0 else 0.0


def _trend_signature(scan_results_df: pd.DataFrame, symbol: str, intervals: List[str]) -> tuple:
    per_symbol = scan_results_df[scan_results_df["symbol"] == symbol]
    trend_map = dict(zip(per_symbol["interval"], per_symbol["trend"]))
    # Include all intervals so signatures are comparable even with sparse inputs.
    return tuple(trend_map.get(interval) for interval in intervals)


def _candles_for_symbol(
    symbol_candle_map: Dict[object, Sequence[Candle]],
    symbol: str,
) -> Sequence[Candle]:
    """Resolve candles for a symbol from either symbol-keyed or tuple-keyed maps."""
    direct = symbol_candle_map.get(symbol)
    if direct is not None:
        return direct

    # Support maps keyed by (symbol, interval) tuples used by scanner routing.
    tuple_candidates: List[Sequence[Candle]] = []
    for key, candles in symbol_candle_map.items():
        if isinstance(key, tuple) and len(key) == 2 and key[0] == symbol:
            tuple_candidates.append(candles)

    if not tuple_candidates:
        return []

    # Prefer the longest available history for stable volume/ATR comparison.
    return max(tuple_candidates, key=len)


def compute_correlation_groups(
    scan_results_df: pd.DataFrame,
    symbol_candle_map: Dict[object, Sequence[Candle]],
) -> pd.DataFrame:
    """Filter correlated symbols and keep one winner per correlation group.

    Correlation definition:
    - Two symbols are correlated when they share the exact same trend direction
      across all intervals present in ``scan_results_df``.

    Winner selection per group follows strict hierarchy:
    1) Highest positive latest-candle volume
    2) Highest ATR (computed on demand via ``compute_atr``)
    3) Alphabetical symbol order
    """
    if scan_results_df.empty:
        return scan_results_df.copy()

    required_columns = {"symbol", "interval", "trend"}
    missing_columns = required_columns - set(scan_results_df.columns)
    if missing_columns:
        raise ValueError(
            f"scan_results_df missing required columns: {sorted(missing_columns)}"
        )

    intervals = sorted(scan_results_df["interval"].dropna().unique().tolist())
    symbols = sorted(scan_results_df["symbol"].dropna().unique().tolist())

    grouped_symbols: Dict[tuple, List[str]] = defaultdict(list)
    for symbol in symbols:
        signature = _trend_signature(scan_results_df, symbol, intervals)
        grouped_symbols[signature].append(symbol)

    winners: set[str] = set()
    for group in grouped_symbols.values():
        ranked = sorted(
            group,
            key=lambda s: (
                -_latest_positive_volume(_candles_for_symbol(symbol_candle_map, s)),
                -compute_atr(_candles_for_symbol(symbol_candle_map, s)),
                s,
            ),
        )
        winners.add(ranked[0])

    filtered = scan_results_df[scan_results_df["symbol"].isin(winners)].copy()
    return filtered.reset_index(drop=True)
