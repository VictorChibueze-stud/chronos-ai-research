"""Market scanner engine for multi-symbol, multi-timeframe trend analysis."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd
import requests
import yaml

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync, get_active_deriv_symbols
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync
from src.core.leg_metrics import annotate_legs_with_metrics, summarise_leg_metrics
from src.core.retracement_depth import annotate_legs_with_depth, summarise_retracement_depths
from src.core.structure_levels import compute_all_structure_levels, compute_internal_structure_levels
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.trend_id import compute_internal_structure, identify_trend
from src.scanner.universe import compute_correlation_groups

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded Deriv universe — always included in every scan regardless of what
# the active_symbols API returns.
# ---------------------------------------------------------------------------
DERIV_FOREX_SYMBOLS = [
    "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxUSDCHF",
    "frxAUDUSD", "frxUSDCAD", "frxNZDUSD", "frxEURGBP",
    "frxEURJPY", "frxGBPJPY",
]

DERIV_COMMODITY_SYMBOLS = [
    "frxXAUUSD", "frxXAGUSD", "frxOILUSD",
]

DERIV_INDICES_SYMBOLS = [
    "OTC_DJI", "OTC_NDX", "OTC_SPX", "OTC_FTSE",
    "OTC_DAX", "OTC_N225",
]

_BINANCE_24H_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
_STABLE_BASE_ASSETS = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD"}
_SYMBOLS_CFG_PATH = Path(__file__).parent.parent.parent / "config" / "symbols.yaml"

RESULT_FIELDS = [
    "symbol",
    "interval",
    "trend",
    "current_phase",
    "confirmed_leg_count",
    "impulse_count",
    "retracement_count",
    "mean_impulse_move_pct",
    "mean_retracement_depth_pct",
    "mean_impulse_duration_candles",
    "mean_retracement_duration_candles",
    "velocity_trend",
    "choch_intact",
    "bos_count",
    "any_choch_risk",
    "anomalous",
    "candle_count",
    "first_candle_ts",
    "last_candle_ts",
    "error",
]

_IMPULSE_OUTLIER_THRESHOLD_PCT = 300.0


def _build_error_result(symbol: str, interval: str, error: str) -> Dict[str, Any]:
    """Build a result payload with all non-id fields set to None for failures."""
    payload: Dict[str, Any] = {field: None for field in RESULT_FIELDS}
    payload["symbol"] = symbol
    payload["interval"] = interval
    payload["error"] = error
    return payload


def fetch_top_symbols(n: int = 350) -> List[str]:
    """Fetch top N USDT pairs by quote volume, excluding stablecoin bases."""
    response = requests.get(_BINANCE_24H_TICKER_URL, timeout=30)
    response.raise_for_status()
    tickers = response.json()

    filtered: List[tuple[str, float]] = []
    for row in tickers:
        symbol = row.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        base_asset = symbol[:-4]
        if base_asset in _STABLE_BASE_ASSETS:
            continue

        try:
            quote_volume = float(row.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            continue

        filtered.append((symbol, quote_volume))

    top = sorted(filtered, key=lambda item: item[1], reverse=True)[:n]
    symbols = [symbol for symbol, _ in top]
    # Avoid print(): Windows cp1252 consoles raise UnicodeEncodeError when the
    # top-N list includes non-ASCII symbol names (e.g. 币安人生USDT), which
    # previously aborted discovery and dropped the entire Binance universe.
    logger.info(
        "Universe: fetched %d USDT pairs by 24h volume (requested cap=%d)",
        len(symbols),
        n,
    )
    return symbols


def run_pipeline(
    symbol: str,
    interval: str,
    candles: List[Any],
    use_parent_relative_filter: bool = True,
    min_impulse_parent_ratio: float = 0.15,
    use_momentum_filter: bool = True,
    min_momentum_ratio: float = 0.5,
    use_dominance_filter: bool = True,
    min_dominance_ratio: float = 1.5,
) -> Dict[str, Any]:
    """Run full trend/structure/metrics pipeline and return a flat scanner payload."""
    try:
        if not candles:
            raise ValueError("candle list is empty")

        result = identify_trend(
            candles,
            use_parent_relative_filter=use_parent_relative_filter,
            min_impulse_parent_ratio=min_impulse_parent_ratio,
            use_momentum_filter=use_momentum_filter,
            min_momentum_ratio=min_momentum_ratio,
            use_dominance_filter=use_dominance_filter,
            min_dominance_ratio=min_dominance_ratio,
        )

        compute_internal_structure(
            candles,
            result["legs"],
            use_parent_relative_filter=use_parent_relative_filter,
            min_impulse_parent_ratio=min_impulse_parent_ratio,
            use_momentum_filter=use_momentum_filter,
            min_momentum_ratio=min_momentum_ratio,
            use_dominance_filter=use_dominance_filter,
            min_dominance_ratio=min_dominance_ratio,
        )

        levels = compute_all_structure_levels(candles, result["legs"], result["trend"])
        compute_internal_structure_levels(candles, result["legs"])
        annotate_legs_with_depth(result["legs"])
        annotate_legs_with_metrics(result["legs"], candles, interval, is_synthetic=False)

        impulse_summary = summarise_leg_metrics(result["legs"], leg_type="impulse")
        retracement_summary = summarise_leg_metrics(result["legs"], leg_type="retracement")
        depth_summary = summarise_retracement_depths(result["legs"])

        # Flag payloads where the mean impulse move looks like bad data.
        mean_imp_move = impulse_summary.get("mean_price_move_pct") if impulse_summary else None
        anomalous = (
            mean_imp_move is not None and mean_imp_move > _IMPULSE_OUTLIER_THRESHOLD_PCT
        )

        confirmed_legs = [leg for leg in result["legs"] if leg.get("confirmed") is True]
        impulse_count = sum(1 for leg in confirmed_legs if leg.get("type") == "impulse")
        retracement_count = sum(1 for leg in confirmed_legs if leg.get("type") == "retracement")

        choch_level = levels.get("choch_level")
        choch_intact = bool(choch_level is not None and choch_level.get("broken") is False)

        return {
            "symbol": symbol,
            "interval": interval,
            "trend": result.get("trend"),
            "current_phase": result.get("current_phase"),
            "confirmed_leg_count": len(confirmed_legs),
            "impulse_count": impulse_count,
            "retracement_count": retracement_count,
            "mean_impulse_move_pct": (
                impulse_summary.get("mean_price_move_pct") if impulse_summary else None
            ),
            "mean_retracement_depth_pct": (
                depth_summary.get("mean_depth_pct") if depth_summary else None
            ),
            "mean_impulse_duration_candles": (
                impulse_summary.get("mean_duration_candles") if impulse_summary else None
            ),
            "mean_retracement_duration_candles": (
                retracement_summary.get("mean_duration_candles") if retracement_summary else None
            ),
            "velocity_trend": impulse_summary.get("velocity_trend") if impulse_summary else None,
            "choch_intact": choch_intact,
            "bos_count": len(levels.get("bos_levels", [])),
            "any_choch_risk": depth_summary.get("any_exceeds_impulse", False)
            if depth_summary
            else False,
            "anomalous": anomalous,
            "candle_count": len(candles),
            "first_candle_ts": candles[0].timestamp.isoformat(),
            "last_candle_ts": candles[-1].timestamp.isoformat(),
            "error": None,
        }
    except Exception as exc:
        return _build_error_result(symbol, interval, str(exc))


def _load_symbols_config() -> Dict[str, Any]:
    """Load symbol universe config from config/symbols.yaml."""
    try:
        with open(_SYMBOLS_CFG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("Failed to read symbols config %s: %s", _SYMBOLS_CFG_PATH, exc)
        return {}


def _section_values(section: Any) -> List[str]:
    """Normalize symbol section formats into a flat list of codes."""
    if isinstance(section, dict):
        return [str(v) for v in section.values()]
    if isinstance(section, list):
        return [str(v) for v in section]
    return []


def _build_symbol_groups(symbols: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split selected symbols into binance and deriv groups using symbols.yaml."""
    cfg = _load_symbols_config()
    configured_binance = set(_section_values(cfg.get("binance", {})))
    configured_deriv = set(_section_values(cfg.get("deriv", {})))

    if symbols:
        requested = set(symbols)
        binance_symbols = sorted(requested & configured_binance)
        deriv_symbols = sorted(requested & configured_deriv)
    else:
        binance_symbols = sorted(configured_binance)
        deriv_symbols = sorted(configured_deriv)

    return binance_symbols, deriv_symbols


def run_scanner(
    symbols: List[str],
    intervals: List[str],
    filter_config: Dict[str, Any],
    force_full: bool = False,
) -> pd.DataFrame:
    """Run scanner over symbols/intervals and persist results + metadata."""
    _ = force_full  # Preserved API; native adapter fetches are always full lookback.

    # Hybrid model: Binance symbols are dynamic (function input),
    # Deriv symbols are static (from config/symbols.yaml).
    binance_symbols = list(symbols)
    cfg = _load_symbols_config()
    yfinance_symbols = sorted(
        {str(s).strip().upper() for s in _section_values(cfg.get("yfinance", [])) if str(s).strip()}
    )
    deriv_symbols = sorted(
        set(_section_values(cfg.get("deriv", {})))
        | set(DERIV_FOREX_SYMBOLS)
        | set(DERIV_COMMODITY_SYMBOLS)
        | set(DERIV_INDICES_SYMBOLS)
    )

    total_combinations = (
        len(binance_symbols) + len(yfinance_symbols) + len(deriv_symbols)
    ) * len(intervals)
    print(
        f"Starting scan: {len(binance_symbols)} binance + {len(yfinance_symbols)} yfinance + "
        f"{len(deriv_symbols)} deriv symbols × {len(intervals)} timeframes = "
        f"{total_combinations} combinations."
    )

    # Deriv validation gate: call active symbol lookup once, drop missing symbols.
    validated_deriv_symbols = list(deriv_symbols)
    if deriv_symbols:
        active_deriv = set(get_active_deriv_symbols())
        missing = sorted(set(deriv_symbols) - active_deriv)
        for symbol in missing:
            logger.warning("Deriv symbol '%s' not active; dropping from fetch queue.", symbol)
        validated_deriv_symbols = sorted(set(deriv_symbols) & active_deriv)

    scan_start = time.perf_counter()
    rows: List[Dict[str, Any]] = []
    symbol_candle_map: Dict[Tuple[str, str], List[Any]] = {}
    fetch_errors: Dict[Tuple[str, str], str] = {}

    # Fetch loop: Binance symbols use Binance adapter.
    for symbol in binance_symbols:
        for interval in intervals:
            try:
                candles = fetch_binance_ohlc_sync(symbol, interval)
                if candles:
                    symbol_candle_map[(symbol, interval)] = candles
                else:
                    fetch_errors[(symbol, interval)] = "empty candle list"
            except Exception as exc:
                fetch_errors[(symbol, interval)] = str(exc)

    for symbol in yfinance_symbols:
        for interval in intervals:
            try:
                candles = fetch_yfinance_ohlc_sync(symbol, interval)
                if candles:
                    symbol_candle_map[(symbol, interval)] = candles
                else:
                    fetch_errors[(symbol, interval)] = "empty candle list"
            except Exception as exc:
                fetch_errors[(symbol, interval)] = str(exc)

    # Fetch loop: validated Deriv symbols use Deriv adapter.
    for symbol in validated_deriv_symbols:
        for interval in intervals:
            try:
                candles = fetch_deriv_ohlc_sync(symbol, interval)
                if candles:
                    symbol_candle_map[(symbol, interval)] = candles
                else:
                    fetch_errors[(symbol, interval)] = "empty candle list"
            except Exception as exc:
                fetch_errors[(symbol, interval)] = str(exc)

    merged_filter = {**SCAN_AND_ANALYSIS_FILTER_DEFAULTS, **filter_config}

    # Core analysis loop over fetched candles.
    for (symbol, interval), candles in symbol_candle_map.items():
        combo_start = time.perf_counter()
        row = run_pipeline(
            symbol,
            interval,
            candles,
            use_parent_relative_filter=bool(
                merged_filter.get("use_parent_relative_filter", True)
            ),
            min_impulse_parent_ratio=float(
                merged_filter.get("min_impulse_parent_ratio", 0.15)
            ),
            use_momentum_filter=bool(merged_filter.get("use_momentum_filter", True)),
            min_momentum_ratio=float(merged_filter.get("min_momentum_ratio", 0.5)),
            use_dominance_filter=bool(merged_filter.get("use_dominance_filter", True)),
            min_dominance_ratio=float(merged_filter.get("min_dominance_ratio", 1.5)),
        )
        rows.append(row)

        elapsed = time.perf_counter() - combo_start
        if row["error"] is None:
            print(
                f"[{symbol}] {interval}: trend={row['trend']} | "
                f"phase={row['current_phase']} | legs={row['confirmed_leg_count']} | "
                f"{elapsed:.1f}s"
            )
        else:
            print(f"[{symbol}] {interval}: ERROR — {row['error']}")

    # Add explicit error rows for combinations that failed during fetch.
    for (symbol, interval), message in fetch_errors.items():
        rows.append(_build_error_result(symbol, interval, message))

    results_df = pd.DataFrame(rows, columns=RESULT_FIELDS)

    # Correlation filter: applied to final scanner results prior to return.
    final_df = compute_correlation_groups(results_df, symbol_candle_map)

    total_time_seconds = time.perf_counter() - scan_start
    successful = int((final_df["error"].isna()).sum()) if not final_df.empty else 0
    failed = int((final_df["error"].notna()).sum()) if not final_df.empty else 0

    successful_df = final_df[final_df["error"].isna()] if not final_df.empty else final_df
    trending_count = int(successful_df["trend"].isin(["up", "down"]).sum()) if not successful_df.empty else 0
    ranging_count = int((successful_df["trend"] == "range").sum()) if not successful_df.empty else 0

    trending_pct = (trending_count / successful * 100.0) if successful else 0.0
    ranging_pct = (ranging_count / successful * 100.0) if successful else 0.0

    minutes = int(total_time_seconds // 60)
    seconds = int(total_time_seconds % 60)

    print("Scan complete.")
    print(f"Total combinations: {total_combinations}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total time: {minutes}m {seconds}s")
    print(f"Trending (up+down): {trending_count} / {successful} ({trending_pct:.1f}%)")
    print(f"Ranging: {ranging_count} / {successful} ({ranging_pct:.1f}%)")

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data") / "scanner" / run_timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / "results.parquet"
    meta_path = output_dir / "scan_meta.json"

    try:
        final_df.to_parquet(parquet_path, index=False)
    except Exception as exc:
        fallback_csv = output_dir / "results.csv"
        final_df.to_csv(fallback_csv, index=False)
        print(
            f"[WARN] Failed to write parquet at {parquet_path}: {exc}. "
            f"Wrote CSV fallback to {fallback_csv}."
        )

    meta = {
        "timestamp": run_timestamp,
        "symbols_scanned": symbols,
        "intervals": intervals,
        "filter_config": filter_config,
        "success_count": successful,
        "failure_count": failed,
        "total_time_seconds": total_time_seconds,
    }

    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    return final_df
