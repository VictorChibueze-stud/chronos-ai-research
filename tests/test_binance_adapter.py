"""Tests for Binance data adapter."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock
import aiohttp

from src.adapters.binance_data import (
    fetch_binance_ohlc,
    fetch_binance_ohlc_sync,
    _parse_kline,
    INTERVAL_TO_MINUTES,
)
from src.core.features import Candle


# Helper to create a mock context manager for async
class AsyncContextManager:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class TestKlineParsing:
    """Test individual kline parsing."""

    def test_candle_field_parsing(self):
        """Parse a single hardcoded kline array with known values."""
        # Binance kline format: [open_time_ms, open, high, low, close, volume, ...]
        kline = [
            1609459200000,  # 2021-01-01 00:00:00 UTC
            "29000.00",     # open
            "30000.00",     # high
            "28500.00",     # low
            "29500.00",     # close
            "100.5",        # volume
            1609545599999,  # close_time
            "3000000",      # quote asset volume
            100,            # number of trades
            "50.25",        # taker buy base asset volume
            "1500000",      # taker buy quote asset volume
            "0",            # unused
        ]

        candle = _parse_kline(kline)

        assert isinstance(candle, Candle)
        assert candle.open == 29000.00
        assert candle.high == 30000.00
        assert candle.low == 28500.00
        assert candle.close == 29500.00
        assert candle.volume == 100.5
        assert candle.timestamp == datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_candle_field_parsing_different_values(self):
        """Parse kline with different values to ensure correct field mapping."""
        kline = [
            1640995200000,  # 2022-01-01
            "16000.50",
            "16500.75",
            "15800.25",
            "16200.00",
            "250.1234",
        ]

        candle = _parse_kline(kline)

        assert candle.open == 16000.50
        assert candle.high == 16500.75
        assert candle.low == 15800.25
        assert candle.close == 16200.00
        assert candle.volume == 250.1234
        assert candle.timestamp == datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class TestSinglePageFetch:
    """Test single page fetch without pagination."""

    @pytest.mark.asyncio
    async def test_single_page_fetch(self):
        """Mock aiohttp to return a list of fake klines, verify single fetch."""
        # Generate 200 fake klines
        fake_klines = []
        base_time = 1609459200000  # 2021-01-01
        for i in range(200):
            kline = [
                base_time + (i * 300000),  # 5m interval in ms
                f"{29000 + i * 10}",  # open (incrementing)
                f"{29500 + i * 10}",  # high
                f"{28500 + i * 10}",  # low
                f"{29250 + i * 10}",  # close
                "100",  # volume
            ]
            fake_klines.append(kline)

        # Mock aiohttp to return single batch
        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=fake_klines)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = await fetch_binance_ohlc("BTCUSDT", "5m")

            assert isinstance(candles, list)
            assert len(candles) == 200
            assert all(isinstance(c, Candle) for c in candles)
            # Verify timestamps are sorted ascending
            for i in range(len(candles) - 1):
                assert candles[i].timestamp <= candles[i + 1].timestamp

    @pytest.mark.asyncio
    async def test_single_page_fetch_timestamps_sorted(self):
        """Verify returned candles are sorted by timestamp."""
        # Create 50 klines with timestamps
        fake_klines = []
        base_time = 1640995200000
        for i in range(50):
            kline = [
                base_time + (i * 3600000),  # 1h interval
                "16000",
                "16500",
                "15800",
                "16200",
                "100",
            ]
            fake_klines.append(kline)

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=fake_klines)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = await fetch_binance_ohlc("BTCUSDT", "1h")

            # Verify ascending order
            for i in range(len(candles) - 1):
                assert candles[i].timestamp < candles[i + 1].timestamp


class TestPagination:
    """Test pagination logic when candle_count > 1000."""

    @pytest.mark.asyncio
    async def test_pagination_triggers(self):
        """Trigger pagination: first request returns 1000, second returns 500."""
        # First batch: 1000 klines
        first_batch = []
        base_time = 1640995200000
        for i in range(1000):
            kline = [
                base_time + (i * 3600000),
                "16000",
                "16500",
                "15800",
                "16200",
                "100",
            ]
            first_batch.append(kline)

        # Second batch: 500 klines (earlier in time)
        second_batch = []
        for i in range(500):
            kline = [
                base_time - ((500 - i) * 3600000),  # go back in time
                "15900",
                "16400",
                "15700",
                "16100",
                "100",
            ]
            second_batch.append(kline)

        call_count = [0]
        request_params = []

        def make_response(batch):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=batch)
            return mock_resp

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            request_params.append(kwargs.get("params", {}))

            if call_count[0] == 1:
                return AsyncContextManager(make_response(first_batch))
            else:
                return AsyncContextManager(make_response(second_batch))

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=mock_get)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = await fetch_binance_ohlc("BTCUSDT", "1h")

            # Verify pagination happened
            assert call_count[0] == 2
            # Verify second call had endTime parameter
            second_params = request_params[1]
            assert "endTime" in second_params

    @pytest.mark.asyncio
    async def test_pagination_endtime_computation(self):
        """Verify that endTime is set to (earliest_timestamp - 1ms) for second page."""
        first_batch = []
        base_time = 1640995200000
        for i in range(1000):
            kline = [
                base_time + (i * 3600000),
                "16000",
                "16500",
                "15800",
                "16200",
                "100",
            ]
            first_batch.append(kline)

        second_batch = []
        for i in range(100):
            kline = [
                base_time - ((100 - i) * 3600000),
                "16000",
                "16500",
                "15800",
                "16200",
                "100",
            ]
            second_batch.append(kline)

        request_params = []

        def make_response(batch):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=batch)
            return mock_resp

        def mock_get(*args, **kwargs):
            request_params.append(kwargs.get("params", {}))

            if len(request_params) == 1:
                return AsyncContextManager(make_response(first_batch))
            else:
                return AsyncContextManager(make_response(second_batch))

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=mock_get)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            await fetch_binance_ohlc("BTCUSDT", "1h")

            # The second request should have endTime = (earliest of first batch - 1ms)
            assert len(request_params) >= 2
            first_batch_earliest_ms = first_batch[0][0]
            expected_end_time = first_batch_earliest_ms - 1

            assert request_params[1].get("endTime") == expected_end_time


class TestRetryLogic:
    """Test retry logic on failure."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Verify retries on aiohttp.ClientError."""
        fake_klines = []
        base_time = 1640995200000
        for i in range(100):
            kline = [base_time + (i * 3600000), "16000", "16500", "15800", "16200", "100"]
            fake_klines.append(kline)

        call_count = [0]

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call fails with a network error
                raise aiohttp.ClientError("Network error")
            else:
                # Second call succeeds
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value=fake_klines)
                return AsyncContextManager(mock_resp)

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=mock_get)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            # Should succeed on second attempt
            candles = await fetch_binance_ohlc("BTCUSDT", "1h")
            assert len(candles) == 100
            assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retry_on_http_error(self):
        """Verify retries on HTTP error status codes."""
        fake_klines = []
        base_time = 1640995200000
        for i in range(50):
            kline = [base_time + (i * 3600000), "16000", "16500", "15800", "16200", "100"]
            fake_klines.append(kline)

        call_count = [0]

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            mock_resp = AsyncMock()

            if call_count[0] <= 2:
                # First two calls return error
                mock_resp.status = 500
            else:
                # Third call succeeds
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value=fake_klines)

            return AsyncContextManager(mock_resp)

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=mock_get)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = await fetch_binance_ohlc("BTCUSDT", "1h")
            assert len(candles) == 50
            assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises(self):
        """Verify that exhausting retries raises an error."""
        def mock_get(*args, **kwargs):
            raise aiohttp.ClientError("Persistent network error")

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = MagicMock(side_effect=mock_get)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            with pytest.raises(aiohttp.ClientError):
                await fetch_binance_ohlc("BTCUSDT", "1h")


class TestUnsupportedInterval:
    """Test error handling for unsupported intervals."""

    def test_unsupported_interval_raises(self):
        """Call with unsupported interval, assert ValueError."""
        with pytest.raises(ValueError) as exc_info:
            fetch_binance_ohlc_sync("BTCUSDT", "3m")

        assert "3m" in str(exc_info.value)
        assert "Unsupported interval" in str(exc_info.value)

    def test_unsupported_interval_async(self):
        """Async version also raises on unsupported interval."""
        import asyncio

        with pytest.raises(ValueError) as exc_info:
            asyncio.run(fetch_binance_ohlc("BTCUSDT", "2h"))

        assert "2h" in str(exc_info.value)

    def test_supported_intervals_accepted(self):
        """Verify that all supported intervals don't raise ValueError on parsing."""
        # We only check that ValueError about unsupported interval is NOT raised
        # The actual fetch will be mocked elsewhere
        import asyncio

        for interval in INTERVAL_TO_MINUTES.keys():
            with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value=[])

                mock_session = AsyncMock()
                mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)

                mock_session_class.return_value = mock_session

                # This should not raise ValueError about unsupported interval
                result = asyncio.run(fetch_binance_ohlc("BTCUSDT", interval))
                assert isinstance(result, list)


class TestSyncWrapper:
    """Test the synchronous wrapper function."""

    def test_fetch_binance_ohlc_sync_returns_candles(self):
        """Verify sync wrapper returns Candle list."""
        fake_klines = []
        base_time = 1640995200000
        for i in range(50):
            kline = [base_time + (i * 3600000), "16000", "16500", "15800", "16200", "100"]
            fake_klines.append(kline)

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=fake_klines)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = fetch_binance_ohlc_sync("BTCUSDT", "1h")

            assert isinstance(candles, list)
            assert len(candles) == 50
            assert all(isinstance(c, Candle) for c in candles)


class TestDeduplication:
    """Test that duplicate candles (by timestamp) are removed."""

    @pytest.mark.asyncio
    async def test_deduplication_by_timestamp(self):
        """Verify duplicates by timestamp are removed."""
        # Create klines with one duplicate timestamp
        base_time = 1640995200000
        kline1 = [base_time, "16000", "16500", "15800", "16200", "100"]
        kline1_dup = [base_time, "16100", "16600", "15900", "16300", "150"]  # Different prices, same time
        kline2 = [base_time + 3600000, "16200", "16700", "16000", "16400", "110"]

        all_klines = [kline1, kline1_dup, kline2]

        with patch("src.adapters.binance_data.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=all_klines)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            candles = await fetch_binance_ohlc("BTCUSDT", "1h")

            # Should have only 2 unique timestamps
            assert len(candles) == 2
            assert candles[0].timestamp == candles[0].timestamp
            assert candles[1].timestamp != candles[0].timestamp
