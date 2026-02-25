"""Fetch OHLC data from Deriv and save as CSV files.

Usage:
    python scripts/fetch_and_save.py [--symbol R_10] [--symbol R_25]

Requires .env with DERIV_APP_ID and DERIV_API_TOKEN set.

Output: data/processed/{symbol}_{timeframe}.csv
        columns: timestamp, open, high, low, close, volume
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Make project root importable when running as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.adapters.deriv_data import DerivConfig, fetch_deriv_ohlc  # noqa: E402

# ---------------------------------------------------------------------------
# Timeframe definitions
# ---------------------------------------------------------------------------

# granularity_sec, lookback_days, label used in filename
TIMEFRAMES = [
    ("1m",  60,     1.5),
    ("5m",  300,    7.5),
    ("15m", 900,    25.0),
    ("1H",  3600,   100.0),
    ("4H",  14400,  365.0),
    ("D",   86400,  365.0 * 6),
]

# Default symbols to fetch (Deriv broker codes)
DEFAULT_SYMBOLS = ["R_10"]


def candles_to_df(candles) -> pd.DataFrame:
    rows = [
        {
            "timestamp": c.timestamp.isoformat(),
            "open":      c.open,
            "high":      c.high,
            "low":       c.low,
            "close":     c.close,
            "volume":    c.volume,
        }
        for c in candles
    ]
    return pd.DataFrame(rows)


def fetch_symbol(symbol: str, cfg: DerivConfig, out_dir: Path) -> None:
    now = datetime.now(tz=timezone.utc)

    for label, granularity_sec, lookback_days in TIMEFRAMES:
        start = now - timedelta(days=lookback_days)
        end   = now

        print(
            f"  [{label}] fetching {lookback_days:.0f} days  "
            f"({start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')})  "
            f"granularity={granularity_sec}s ...",
            end=" ",
            flush=True,
        )

        try:
            candles = fetch_deriv_ohlc(
                symbol_code=symbol,
                granularity_sec=granularity_sec,
                start=start,
                end=end,
                cfg=cfg,
            )
        except Exception as exc:
            print(f"ERROR: {exc}")
            continue

        if not candles:
            print("0 candles returned — skipping")
            continue

        df       = candles_to_df(candles)
        filename = out_dir / f"{symbol}_{label}.csv"
        df.to_csv(filename, index=False)
        print(f"{len(candles)} candles -> {filename.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Deriv OHLC and save to CSV")
    parser.add_argument(
        "--symbol",
        dest="symbols",
        action="append",
        metavar="CODE",
        help="Deriv symbol code (e.g. R_10, R_25). Repeatable. Default: R_10",
    )
    args = parser.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS

    # Load .env from project root
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"ERROR: .env file not found at {env_path}")
        print("       Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    load_dotenv(env_path)

    try:
        cfg = DerivConfig.from_env()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir.relative_to(ROOT)}\n")

    for symbol in symbols:
        print(f"=== {symbol} ===")
        fetch_symbol(symbol, cfg, out_dir)
        print()

    print("Done.")


if __name__ == "__main__":
    main()
