"""Exploration harness to visualize features computed by src.core.features.

Run as: python -m exploration.feature_explorer

Configure SYMBOL, TIMEFRAME, and CSV_PATH at the top of the file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import pandas as pd

from src.core.features import Candle, normalize_candles, compute_price_features

# Configuration (edit as needed)
SYMBOL = "DEMO"
TIMEFRAME = "15m"
CSV_PATH = "data/raw/demo_ohlc.csv"


def load_csv_to_candles(path: str) -> List[Candle]:
    df = pd.read_csv(path)
    # Expect columns: timestamp, open, high, low, close, optional volume
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "timestamp": r.get("timestamp") or r.get("time") or r.get("date"),
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close"),
            "volume": r.get("volume", 0.0),
        })
    return normalize_candles(rows)


def plot_swings(times, closes, swings, out_path: Path):
    plt.figure(figsize=(12, 6))
    plt.plot(times, closes, label="close")
    for s in swings:
        idx = s["index"]
        plt.scatter(times[idx], closes[idx], marker=("^" if s["type"] == "HH" else "v"), s=100, label=s["type"])
    plt.title(f"{SYMBOL} Swings {TIMEFRAME}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_bos(times, closes, ict_events, out_path: Path):
    plt.figure(figsize=(12, 6))
    plt.plot(times, closes, label="close")
    for e in ict_events:
        if e.get("type") == "BOS":
            plt.axvline(times[e["index"]], color=("g" if e["direction"] == "bull" else "r"), linestyle="--", alpha=0.7)
    plt.title(f"{SYMBOL} BOS/CHOCH {TIMEFRAME}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_fvg(times, highs, lows, fvg_list, out_path: Path):
    plt.figure(figsize=(12, 6))
    mid = [(h + l) / 2.0 for h, l in zip(highs, lows)]
    plt.plot(times, mid, label="price_mid")
    ax = plt.gca()
    for f in fvg_list:
        start = f["start"]
        end = f["end"]
        if f["type"] == "bull":
            ax.axvspan(times[start], times[end], color="green", alpha=0.2)
        else:
            ax.axvspan(times[start], times[end], color="red", alpha=0.2)
    plt.title(f"{SYMBOL} FVG {TIMEFRAME}")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def main():
    outdir = Path("data/processed/plots")
    outdir.mkdir(parents=True, exist_ok=True)

    if not Path(CSV_PATH).exists():
        # create a tiny synthetic CSV for demo purposes
        demo = pd.DataFrame({
            "timestamp": pd.date_range(end=pd.Timestamp.now(tz=None), periods=100, freq="15T"),
            "open": list(range(100)),
            "high": [i + 0.5 for i in range(100)],
            "low": [i - 0.5 for i in range(100)],
            "close": list(range(100)),
        })
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        demo.to_csv(CSV_PATH, index=False)

    candles = load_csv_to_candles(CSV_PATH)
    features = compute_price_features(candles, timeframe=TIMEFRAME)

    times = [c.timestamp for c in candles]
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    swings = features["structure_map"]["swings"]
    ict = features["ict_events"]
    fvg = features["structure_map"]["fvg"]

    # save plots
    plot_swings(times, closes, swings, outdir / f"chronos_{SYMBOL}_swings_{TIMEFRAME}.png")
    plot_bos(times, closes, ict, outdir / f"chronos_{SYMBOL}_bos_{TIMEFRAME}.png")
    plot_fvg(times, highs, lows, fvg, outdir / f"chronos_{SYMBOL}_fvg_{TIMEFRAME}.png")

    print("Saved plots to:", outdir)


if __name__ == "__main__":
    main()
