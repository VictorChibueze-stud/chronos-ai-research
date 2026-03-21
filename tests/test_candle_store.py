"""Test suite for candle_store module.

All tests use temporary directories (tmp_path) for file I/O.
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.data.candle_store import (
    can_resample,
    resample_candles,
    get_candle_path,
    load_candles,
    save_candles,
    get_last_fetch_timestamp,
    estimate_fetch_time,
    candles_df_to_candle_list,
    fetch_and_store,
    CANDLE_STORE_PATH,
)
from src.core.features import Candle


class TestResample:
    """Tests for resampling logic."""

    def test_resample_5m_to_1h(self):
        """Build 12 synthetic 5M candles (one hour) and resample to 1H."""
        # Create 12 x 5-minute candles covering exactly 1 hour
        timestamps = pd.date_range("2026-01-01 10:00:00", periods=12, freq="5min", tz="UTC")
        data = {
            "open": [100.0 + i for i in range(12)],
            "high": [105.0 + i for i in range(12)],
            "low": [95.0 + i for i in range(12)],
            "close": [102.0 + i for i in range(12)],
            "volume": [1000.0 + i * 100 for i in range(12)],
        }
        df_5m = pd.DataFrame(data, index=timestamps)
        df_5m.index.name = "timestamp"

        # Resample to 1H
        df_1h = resample_candles(df_5m, "1h")

        # Assert exactly 1 row
        assert len(df_1h) == 1, f"Expected 1 row, got {len(df_1h)}"

        # Check OHLC values
        row = df_1h.iloc[0]
        assert row["open"] == 100.0, "Open should be first 5M open"
        assert row["close"] == 113.0, "Close should be last 5M close"
        assert row["high"] == 116.0, "High should be max of all highs"
        assert row["low"] == 95.0, "Low should be min of all lows"
        # volume = sum([1000 + i*100 for i in range(12)]) = 18600
        assert row["volume"] == pytest.approx(18600.0), "Volume should be sum of all volumes"

    def test_resample_drops_incomplete_period(self):
        """Build 14 synthetic 5M candles (12 complete + 2 incomplete 1H).

        Assert resampled 1H result has exactly 1 complete row, not 2.
        """
        # 14 x 5-minute candles = 70 minutes = 1 complete hour + 10 minutes incomplete
        timestamps = pd.date_range("2026-01-01 10:00:00", periods=14, freq="5min", tz="UTC")
        data = {
            "open": [100.0 + i for i in range(14)],
            "high": [105.0 + i for i in range(14)],
            "low": [95.0 + i for i in range(14)],
            "close": [102.0 + i for i in range(14)],
            "volume": [1000.0 for _ in range(14)],
        }
        df_5m = pd.DataFrame(data, index=timestamps)
        df_5m.index.name = "timestamp"

        # Resample to 1H
        df_1h = resample_candles(df_5m, "1h")

        # Assert exactly 1 complete row (the incomplete second hour is dropped)
        assert len(df_1h) == 1, f"Expected 1 complete row, got {len(df_1h)}"

    def test_can_resample_false_when_base_insufficient(self):
        """Mock timeframe_windows.yaml so 5m has lookback_days=7.5 and 1h has lookback_days=100.

        Assert can_resample("5m", "1h", config) returns False.
        """
        config = {
            "timeframes": {
                "5m": {"lookback_days": 7.5},
                "1h": {"lookback_days": 100.0},
            }
        }
        result = can_resample("5m", "1h", config)
        assert result is False, "5m lookback (7.5d) insufficient for 1h lookback (100d)"

    def test_can_resample_true_when_base_sufficient(self):
        """Mock config so 1h has lookback_days=200 and 4h has lookback_days=100.

        Assert can_resample("1h", "4h", config) returns True.
        """
        config = {
            "timeframes": {
                "1h": {"lookback_days": 200.0},
                "4h": {"lookback_days": 100.0},
            }
        }
        result = can_resample("1h", "4h", config)
        assert result is True, "1h lookback (200d) sufficient for 4h lookback (100d)"


class TestFileIO:
    """Tests for parquet save/load and metadata tracking."""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Save a small DataFrame, load it back, assert data matches."""
        # Temporarily override CANDLE_STORE_PATH
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        # Create a small test DataFrame
        timestamps = pd.date_range("2026-01-01 10:00:00", periods=5, freq="1h", tz="UTC")
        data = {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [105.0, 106.0, 107.0, 108.0, 109.0],
            "low": [95.0, 96.0, 97.0, 98.0, 99.0],
            "close": [102.0, 103.0, 104.0, 105.0, 106.0],
            "volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
        }
        df_orig = pd.DataFrame(data, index=timestamps)
        df_orig.index.name = "timestamp"

        # Save
        save_candles("BTCUSDT", "1h", df_orig)

        # Load
        df_loaded = load_candles("BTCUSDT", "1h")

        # Assert data matches
        assert df_loaded is not None
        assert len(df_loaded) == 5
        assert df_loaded["open"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]
        assert df_loaded["close"].tolist() == [102.0, 103.0, 104.0, 105.0, 106.0]
        pd.testing.assert_index_equal(df_loaded.index, df_orig.index)

    def test_save_deduplicates(self, tmp_path, monkeypatch):
        """Save a DataFrame with duplicate timestamps. Assert no duplicates in loaded result."""
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        # Create DataFrame with duplicate timestamps (keep last)
        timestamps = pd.DatetimeIndex(
            ["2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-01 11:00:00"],
            tz="UTC",
        )
        data = {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [1000.0, 1100.0, 1200.0],
        }
        df = pd.DataFrame(data, index=timestamps)
        df.index.name = "timestamp"

        # Save (should deduplicate, keeping last)
        save_candles("BTCUSDT", "1h", df)

        # Load and check
        df_loaded = load_candles("BTCUSDT", "1h")
        assert df_loaded is not None
        assert len(df_loaded) == 2, "Should have 2 rows after deduplication"
        assert df_loaded.index[-1].hour == 11
        assert df_loaded.loc[df_loaded.index[-1], "close"] == 104.0, "Should keep last close value"

    def test_metadata_updated_on_save(self, tmp_path, monkeypatch):
        """After save_candles, read metadata.json and assert it's updated."""
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        timestamps = pd.date_range("2026-01-01 10:00:00", periods=3, freq="1h", tz="UTC")
        data = {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [1000.0, 1100.0, 1200.0],
        }
        df = pd.DataFrame(data, index=timestamps)
        df.index.name = "timestamp"

        # Save
        save_candles("BTCUSDT", "1h", df)

        # Read metadata.json
        metadata_path = tmp_path / "BTCUSDT" / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as fh:
            metadata = json.load(fh)

        # Check metadata structure
        assert metadata["symbol"] == "BTCUSDT"
        assert metadata["is_synthetic"] is False
        assert "last_fetch" in metadata
        assert "candle_counts" in metadata
        assert metadata["last_fetch"]["1h"] == timestamps[-1].isoformat()
        assert metadata["candle_counts"]["1h"] == 3

    def test_get_last_fetch_returns_none_when_missing(self, tmp_path, monkeypatch):
        """Call get_last_fetch_timestamp on a symbol with no metadata. Assert returns None."""
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        # Symbol with no metadata
        result = get_last_fetch_timestamp("UNKNOWN", "1h")
        assert result is None


class TestConversion:
    """Tests for DataFrame to Candle list conversion."""

    def test_candles_df_to_candle_list(self):
        """Build a 5-row DataFrame, convert to List[Candle], assert fields match."""
        timestamps = pd.date_range("2026-01-01 10:00:00", periods=5, freq="1h", tz="UTC")
        data = {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [105.0, 106.0, 107.0, 108.0, 109.0],
            "low": [95.0, 96.0, 97.0, 98.0, 99.0],
            "close": [102.0, 103.0, 104.0, 105.0, 106.0],
            "volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
        }
        df = pd.DataFrame(data, index=timestamps)
        df.index.name = "timestamp"

        # Convert
        candles = candles_df_to_candle_list(df)

        # Assert
        assert len(candles) == 5
        assert candles[0].timestamp == timestamps[0].to_pydatetime()
        assert candles[0].open == 100.0
        assert candles[0].high == 105.0
        assert candles[0].low == 95.0
        assert candles[0].close == 102.0
        assert candles[0].volume == 1000.0


class TestEstimate:
    """Tests for fetch time estimation."""

    def test_estimate_fetch_time_returns_all_keys(self):
        """Call estimate_fetch_time with sample symbols/intervals. Assert result has all keys."""
        result = estimate_fetch_time(["BTCUSDT"], ["1h", "4h"])

        assert "total_requests_estimated" in result
        assert "estimated_seconds" in result
        assert "estimated_human" in result
        assert "breakdown" in result

        # breakdown should have entries for intervals that require direct fetch
        assert isinstance(result["breakdown"], dict)
        assert isinstance(result["total_requests_estimated"], int)
        assert isinstance(result["estimated_seconds"], (int, float))
        assert isinstance(result["estimated_human"], str)


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_get_candle_path_creates_dirs(self, tmp_path, monkeypatch):
        """get_candle_path should create parent directories."""
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        path = get_candle_path("BTCUSDT", "1h")
        assert path.parent.exists(), "Parent directory should be created"
        assert path == tmp_path / "BTCUSDT" / "1h.parquet"

    def test_load_returns_none_for_missing_file(self, tmp_path, monkeypatch):
        """load_candles should return None if file doesn't exist."""
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        result = load_candles("NONEXISTENT", "1h")
        assert result is None


class TestIncremental:
    """Tests for incremental fetch behaviour in fetch_and_store."""

    def test_incremental_fetch_uses_start_time(self, tmp_path, monkeypatch):
        """When metadata has a prior last_fetch_ts and force_full=False,
        fetch_binance_ohlc_sync must be called with a non-None start_time.
        This verifies the incremental branch passes the timestamp to the adapter
        instead of doing a silent full refetch.
        """
        monkeypatch.setattr("src.data.candle_store.CANDLE_STORE_PATH", tmp_path)

        # Build an initial parquet file + metadata so there IS a prior fetch timestamp.
        prior_ts = datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
        timestamps_init = pd.date_range(
            "2026-01-01 00:00:00", periods=10, freq="1h", tz="UTC"
        )
        df_init = pd.DataFrame(
            {
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.5] * 10,
                "volume": [1000.0] * 10,
            },
            index=timestamps_init,
        )
        df_init.index.name = "timestamp"
        save_candles("BTCUSDT", "1h", df_init)

        # Capture what start_time fetch_binance_ohlc_sync was called with.
        captured_start_times = []

        def _mock_fetch(symbol, interval, start_time=None):
            captured_start_times.append(start_time)
            # Return one new candle after the last stored candle.
            new_ts = prior_ts + timedelta(hours=1)
            return [
                Candle(
                    timestamp=new_ts,
                    open=105.0,
                    high=106.0,
                    low=104.0,
                    close=105.5,
                    volume=500.0,
                )
            ]

        monkeypatch.setattr(
            "src.data.candle_store.fetch_binance_ohlc_sync", _mock_fetch
        )

        # Perform incremental fetch (force_full=False, no RESAMPLE_MAP entry for "1h").
        monkeypatch.setitem(
            __import__("src.data.candle_store", fromlist=["RESAMPLE_MAP"]).RESAMPLE_MAP,
            "1h",
            None,
        )
        # Remove "1h" from RESAMPLE_MAP so we hit the direct-fetch path.
        import src.data.candle_store as cs_mod
        original_resample_map = dict(cs_mod.RESAMPLE_MAP)
        cs_mod.RESAMPLE_MAP.pop("1h", None)

        try:
            fetch_and_store("BTCUSDT", "1h", force_full=False)
        finally:
            cs_mod.RESAMPLE_MAP.update(original_resample_map)

        # Assert that at least one call was made with a non-None start_time.
        assert len(captured_start_times) >= 1, "fetch_binance_ohlc_sync was never called"
        assert captured_start_times[0] is not None, (
            "Expected start_time to be non-None for incremental fetch, got None "
            "(incremental branch is doing a silent full refetch)"
        )
