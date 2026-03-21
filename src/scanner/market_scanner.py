"""Market scanner engine for multi-symbol, multi-timeframe trend analysis."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
import yaml

from src.core.leg_metrics import annotate_legs_with_metrics, summarise_leg_metrics
from src.core.retracement_depth import annotate_legs_with_depth, summarise_retracement_depths
from src.core.structure_levels import compute_all_structure_levels, compute_internal_structure_levels
from src.core.trend_id import compute_internal_structure, identify_trend
from src.data.candle_store import (
    candles_df_to_candle_list,
    estimate_fetch_time,
    fetch_and_store_all_intervals,
)

_BINANCE_24H_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
_STABLE_BASE_ASSETS = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD"}

# Load timeframe config for lookback-based candle filtering.
_TF_CFG_PATH = Path(__file__).parent.parent.parent / "config" / "timeframe_windows.yaml"
try:
    with open(_TF_CFG_PATH) as _f:
        _TF_CFG = yaml.safe_load(_f)["timeframes"]
except Exception:
    _TF_CFG = {}

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


def fetch_top_symbols(n: int = 50) -> List[str]:
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
    print(f"Universe: top {n} USDT pairs by 24h volume fetched. {symbols}")
    return symbols


def run_pipeline(
    symbol: str,
    interval: str,
    candles: List[Any],
    use_parent_relative_filter: bool = False,
    min_impulse_parent_ratio: float = 0.15,
    use_momentum_filter: bool = False,
    min_momentum_ratio: float = 0.3,
    use_dominance_filter: bool = False,
    min_dominance_ratio: float = 1.2,
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


def run_scanner(
    symbols: List[str],
    intervals: List[str],
    filter_config: Dict[str, Any],
    force_full: bool = False,
) -> pd.DataFrame:
    """Run scanner over symbols/intervals and persist results + metadata."""
    estimate = estimate_fetch_time(symbols, intervals)
    print("Fetch estimate:")
    print(json.dumps(estimate, indent=2))

    total_combinations = len(symbols) * len(intervals)
    print(
        f"Starting scan: {len(symbols)} symbols × {len(intervals)} timeframes = "
        f"{total_combinations} combinations."
    )

    scan_start = time.perf_counter()
    rows: List[Dict[str, Any]] = []

    for symbol in symbols:
        symbol_start = time.perf_counter()
        try:
            interval_frames = fetch_and_store_all_intervals(
                symbol,
                intervals,
                force_full=force_full,
            )
        except Exception as exc:
            message = f"fetch_and_store_all_intervals failed: {exc}"
            for interval in intervals:
                error_row = _build_error_result(symbol, interval, message)
                rows.append(error_row)
                print(f"[{symbol}] {interval}: ERROR — {message}")
            continue

        for interval in intervals:
            combo_start = time.perf_counter()
            try:
                frame = interval_frames.get(interval)
                if frame is None:
                    raise ValueError(f"missing candle frame for interval={interval}")

                candles = candles_df_to_candle_list(frame)

                # Apply lookback filter to avoid pipeline running on stale data.
                if interval in _TF_CFG and len(candles) > 0:
                    lookback_days = _TF_CFG[interval]["lookback_days"]
                    cutoff = candles[-1].timestamp - timedelta(days=lookback_days)
                    candles = [c for c in candles if c.timestamp >= cutoff]
                    if len(candles) < 50:
                        print(
                            f"[{symbol}] {interval}: SKIP — only {len(candles)} candles "
                            f"after lookback filter"
                        )
                        continue

                row = run_pipeline(
                    symbol,
                    interval,
                    candles,
                    use_parent_relative_filter=bool(
                        filter_config.get("use_parent_relative_filter", False)
                    ),
                    min_impulse_parent_ratio=float(
                        filter_config.get("min_impulse_parent_ratio", 0.15)
                    ),
                    use_momentum_filter=bool(filter_config.get("use_momentum_filter", False)),
                    min_momentum_ratio=float(filter_config.get("min_momentum_ratio", 0.3)),
                    use_dominance_filter=bool(filter_config.get("use_dominance_filter", False)),
                    min_dominance_ratio=float(filter_config.get("min_dominance_ratio", 1.2)),
                )
            except Exception as exc:
                row = _build_error_result(symbol, interval, str(exc))

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

        symbol_elapsed = time.perf_counter() - symbol_start
        print(f"[{symbol}] done in {symbol_elapsed:.1f}s")

    results_df = pd.DataFrame(rows, columns=RESULT_FIELDS)

    total_time_seconds = time.perf_counter() - scan_start
    successful = int((results_df["error"].isna()).sum()) if not results_df.empty else 0
    failed = int((results_df["error"].notna()).sum()) if not results_df.empty else 0

    successful_df = results_df[results_df["error"].isna()] if not results_df.empty else results_df
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
        results_df.to_parquet(parquet_path, index=False)
    except Exception as exc:
        fallback_csv = output_dir / "results.csv"
        results_df.to_csv(fallback_csv, index=False)
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

    return results_df
