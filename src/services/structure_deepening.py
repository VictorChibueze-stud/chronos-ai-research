"""Iterative lower-TF internal structure deepening (15m / 5m).

Shared by GET /api/analysis and CHoCH candidate move slice processing.
"""
from __future__ import annotations

import logging
from typing import Any

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.core.trend_id import compute_internal_structure, identify_trend

INTERNAL_TF_ORDER = ["15m", "5m"]

logger = logging.getLogger(__name__)


def trend_kw_without_tcp(cfg: dict[str, Any]) -> dict[str, Any]:
    """Drop trend_confirmation_pct so callers can pass a fixed tcp (e.g. 0.005)."""
    return {k: v for k, v in cfg.items() if k != "trend_confirmation_pct"}


def apply_tf_deepening_to_legs(
    candles: list,
    legs: list,
    filter_config: dict[str, Any],
    symbol: str,
) -> None:
    """
    For each confirmed impulse leg with fewer than two confirmed internal legs,
    try 15m then 5m over the impulse window; attach internal_structure when successful.
    Mutates legs in place. Expects leg indices relative to ``candles``.
    """
    sym = symbol.upper()
    is_binance = sym.endswith("USDT") or sym.endswith("BTC")
    if is_binance:
        fetch_fn = fetch_binance_ohlc_sync
    elif is_yfinance_symbol(sym):
        fetch_fn = fetch_yfinance_ohlc_sync
    else:
        fetch_fn = fetch_deriv_ohlc_sync

    n_main = len(candles)

    for leg in legs:
        if leg.get("type") != "impulse" or not leg.get("confirmed"):
            continue
        if leg.get("end_index") is None:
            continue

        start_idx = int(leg["start_index"])
        end_idx = int(leg["end_index"])
        if start_idx < 0 or end_idx >= n_main or end_idx < start_idx:
            continue

        internal = leg.get("internal_structure")
        confirmed_internal = [
            x for x in (internal or {}).get("legs", []) if x.get("confirmed")
        ] if internal else []

        if len(confirmed_internal) >= 2:
            continue

        impulse_start_ts = candles[start_idx].timestamp
        impulse_end_ts = candles[end_idx].timestamp

        for tf_key in INTERNAL_TF_ORDER:
            try:
                tf_candles = fetch_fn(sym, tf_key, start_time=impulse_start_ts)
                tf_slice = [
                    c for c in tf_candles if impulse_start_ts <= c.timestamp <= impulse_end_ts
                ]
                if len(tf_slice) < 10:
                    continue

                tf_kw = trend_kw_without_tcp(filter_config)
                tf_result = identify_trend(
                    tf_slice,
                    trend_confirmation_pct=0.005,
                    **tf_kw,
                )
                if tf_result.get("trend") == "range":
                    continue

                compute_internal_structure(
                    tf_slice,
                    tf_result["legs"],
                    trend_confirmation_pct=0.005,
                    **tf_kw,
                )

                tf_confirmed = [x for x in tf_result["legs"] if x.get("confirmed")]
                if len(tf_confirmed) >= 1:
                    leg["internal_structure"] = tf_result
                    leg["internal_tf_used"] = tf_key
                    leg["internal_tf_candles"] = tf_slice
                    break
            except Exception as e:
                logger.warning("TF deepening failed for %s %s: %s", sym, tf_key, e)
                continue
