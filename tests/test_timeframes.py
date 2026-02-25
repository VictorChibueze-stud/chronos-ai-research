from datetime import datetime, timezone
from pathlib import Path

from src.core.timeframes import load_timeframe_windows, get_time_window


def test_load_timeframe_windows_smoke(tmp_path: Path):
    cfg = tmp_path / "timeframe_windows.yaml"
    cfg.write_text(
        """
timeframes:
  "15m":
    lookback_days: 25.0
  "1h":
    lookback_days: 100.0
""",
        encoding="utf-8",
    )

    mapping = load_timeframe_windows(cfg)
    assert "15m" in mapping
    assert mapping["15m"].lookback_days == 25.0


def test_get_time_window_uses_lookback_days(monkeypatch):
    fixed = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    cfg = {"15m": type("T", (), {"lookback_days": 2.0})}

    start, end = get_time_window("15m", now=fixed, config=cfg)
    assert end == fixed
    expected_start = datetime(2023, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
    assert start == expected_start
