import csv
from datetime import datetime

from src.adapters.local_data import load_ohlc_from_csv


def test_load_ohlc_from_csv_basic(tmp_path):
    csv_path = tmp_path / "test_ohlc.csv"
    rows = [
        ["2025-01-01T00:00:00Z", 1.0, 1.2, 0.8, 1.1, 0],
        ["2025-01-01T00:15:00Z", 1.1, 1.3, 0.9, 1.2, 0],
    ]
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)

    candles = load_ohlc_from_csv(csv_path)
    assert len(candles) == 2
    assert candles[0].open == 1.0
    assert candles[1].close == 1.2
    assert candles[0].timestamp < candles[1].timestamp
