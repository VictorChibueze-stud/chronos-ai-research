"""Exploratory EDA for Deriv trend features.

Runnable as: python -m exploration.eda_deriv_trend
"""
from __future__ import annotations

import argparse
import os
from dotenv import load_dotenv
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from src.adapters.deriv_data import fetch_deriv_ohlc
from src.core.features import Candle, compute_price_features, rsi

load_dotenv()


def timeframe_to_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    # fallback: assume minutes
    try:
        return int(tf) * 60
    except Exception:
        raise ValueError("Unsupported timeframe format: %s" % tf)


def draw_candles(ax, candles: List[Candle], width_days: float = 0.0008) -> None:
    xs = [mdates.date2num(c.timestamp) for c in candles]
    for x, c in zip(xs, candles):
        o, h, l, cl = c.open, c.high, c.low, c.close
        color = "#2ca02c" if cl >= o else "#d62728"
        # wick
        ax.vlines(x, l, h, color=color, linewidth=0.5, zorder=1)
        # body
        bottom = min(o, cl)
        height = abs(cl - o)
        rect = Rectangle((x - width_days / 2.0, bottom), width_days, max(height, 1e-9), color=color, linewidth=0, zorder=2)
        ax.add_patch(rect)
    ax.xaxis_date()


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="EDA visualizer for Deriv trend features")
    parser.add_argument("--symbol", type=str, default="R_10")
    parser.add_argument("--timeframe", type=str, default="15m")
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args(argv)

    symbol: str = args.symbol
    timeframe: str = args.timeframe
    days: int = args.days

    end = datetime.utcnow()
    start = end - timedelta(days=days)
    gran = timeframe_to_seconds(timeframe)

    try:
        candles = fetch_deriv_ohlc(symbol, gran, start, end)
    except Exception as exc:
        print(f"Error fetching data: {exc}")
        return 2

    if not candles:
        print("No data returned from Deriv; exiting.")
        return 1

    try:
        features: Dict[str, Any] = compute_price_features(candles, timeframe)
    except Exception as exc:
        print(f"Error computing features: {exc}")
        return 3

    # Summary print
    num_bars = features.get("meta", {}).get("num_candles", len(candles))
    regime = features.get("regime_tags", {})
    structure_map = features.get("structure_map", {})
    ict_events = features.get("ict_events", [])

    # recent swings: try structure_map['swing_highs'] or structure_map['swings']
    swings = structure_map.get("swing_highs") or structure_map.get("swings") or []
    recent_sh = None
    recent_sl = None
    for s in reversed(swings):
        if s.get("type") in ("HH", "SH", "swing_high") and recent_sh is None:
            recent_sh = s
        if s.get("type") in ("LL", "SL", "swing_low") and recent_sl is None:
            recent_sl = s
        if recent_sh and recent_sl:
            break

    print(f"Data fetched: {num_bars} bars")
    if regime:
        if regime.get("is_trending_up"):
            tag = "trending_up"
        elif regime.get("is_trending_down"):
            tag = "trending_down"
        elif regime.get("is_range"):
            tag = "range"
        else:
            tag = str(regime)
    else:
        tag = "unknown"
    print(f"Current Regime: {tag}")
    if recent_sh:
        print(f"Recent Swing High: {recent_sh.get('price')}")
    else:
        print("Recent Swing High: N/A")
    if recent_sl:
        print(f"Recent Swing Low: {recent_sl.get('price')}")
    else:
        print("Recent Swing Low: N/A")

    # Prepare plotting data
    dates = [c.timestamp for c in candles]
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    # Create figure
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 2, 2]})

    # Panel 1: Candles + EMAs
    draw_candles(ax1, candles, width_days=0.0008 * max(1, gran / 60))
    from src.core.features import ema as _ema

    close_arr = [c.close for c in candles]
    ema20_full = _ema(close_arr, 20)
    ema50_full = _ema(close_arr, 50)
    ax1.plot(dates, ema20_full, color="green", label="EMA20")
    ax1.plot(dates, ema50_full, color="red", label="EMA50")
    ax1.legend(loc="upper left")

    # Background color by regime
    regime_tags = features.get("regime_tags", {})
    if regime_tags.get("is_trending_up"):
        ax1.set_facecolor("#eaffea")
    elif regime_tags.get("is_trending_down"):
        ax1.set_facecolor("#ffecec")
    else:
        ax1.set_facecolor("#f0f0f0")

    # Panel 2: Structure
    ax2.plot(dates, closes, color="black", linewidth=1)
    swings_list = structure_map.get("swings", [])
    sh_x = []
    sh_y = []
    sl_x = []
    sl_y = []
    for s in swings_list:
        idx = s.get("index")
        if idx is None:
            continue
        if s.get("type") == "HH":
            sh_x.append(dates[idx])
            sh_y.append(s.get("price"))
        if s.get("type") == "LL":
            sl_x.append(dates[idx])
            sl_y.append(s.get("price"))
    if sh_x:
        ax2.scatter(sh_x, sh_y, marker="^", color="green", label="Swing Highs")
    if sl_x:
        ax2.scatter(sl_x, sl_y, marker="v", color="red", label="Swing Lows")
    # BOS vertical dashed lines
    for e in ict_events:
        if e.get("type") == "BOS":
            idx = e.get("index")
            if idx is None:
                continue
            ax2.axvline(dates[idx], color="#666666", linestyle="--", linewidth=0.8)
    ax2.legend(loc="upper left")

    # Panel 3: RSI and optional FVG zones
    rsi_arr = rsi(closes, 14)
    ax3.plot(dates, rsi_arr, color="purple", label="RSI")
    ax3.axhline(30, color="gray", linestyle="--", linewidth=0.7)
    ax3.axhline(70, color="gray", linestyle="--", linewidth=0.7)
    # FVG shading
    for gap in structure_map.get("fvg", []):
        start_idx = gap.get("start")
        end_idx = gap.get("end")
        if start_idx is None or end_idx is None:
            continue
        ax1.axvspan(dates[start_idx], dates[end_idx], color="#ffffcc", alpha=0.3)

    ax3.legend(loc="upper left")

    # Formatting
    ax3.set_ylim(-5, 105)
    ax3.set_ylabel("RSI")
    ax2.set_ylabel("Price")
    ax1.set_ylabel("Price")
    fig.autofmt_xdate()

    # Save
    out_dir = os.path.join("data", "processed", "plots")
    os.makedirs(out_dir, exist_ok=True)
    date_tag = datetime.utcnow().strftime("%Y%m%d")
    out_path = os.path.join(out_dir, f"eda_{symbol}_{timeframe}_{date_tag}.png")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
