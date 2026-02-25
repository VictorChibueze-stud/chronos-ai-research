from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import yaml


DEFAULT_TIMEFRAME_CONFIG_PATH = Path("config") / "timeframe_windows.yaml"


@dataclass(frozen=True)
class TimeframeWindow:
    """Configuration for a single timeframe's zoom-out window."""
    timeframe: str
    lookback_days: float


def load_timeframe_windows(
    config_path: Optional[Path] = None
) -> Dict[str, TimeframeWindow]:
    """
    Load timeframe windows from YAML and return a dict mapping timeframe -> TimeframeWindow.

    - config_path: optional override, defaults to DEFAULT_TIMEFRAME_CONFIG_PATH.
    - Raises FileNotFoundError if the config file is missing.
    - Raises ValueError if the structure is invalid.
    """
    path = config_path or DEFAULT_TIMEFRAME_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Timeframe config not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "timeframes" not in data:
        raise ValueError("Invalid timeframe config structure: missing 'timeframes' key")

    tf_map: Dict[str, TimeframeWindow] = {}
    timeframes = data.get("timeframes") or {}
    if not isinstance(timeframes, dict):
        raise ValueError("Invalid 'timeframes' mapping in config")

    for tf, cfg in timeframes.items():
        if not isinstance(cfg, dict) or "lookback_days" not in cfg:
            raise ValueError(f"Missing 'lookback_days' for timeframe '{tf}'")

        lookback = cfg["lookback_days"]
        try:
            lookback_f = float(lookback)
        except Exception as exc:
            raise ValueError(f"Invalid lookback_days for '{tf}': {lookback}") from exc

        tf_map[str(tf)] = TimeframeWindow(timeframe=str(tf), lookback_days=lookback_f)

    return tf_map


def get_time_window(
    timeframe: str,
    now: Optional[datetime] = None,
    *,
    config: Optional[Dict[str, TimeframeWindow]] = None,
) -> tuple[datetime, datetime]:
    """
    Return (start, end) datetimes for a given timeframe's canonical zoom-out window.

    - timeframe: e.g. "1m", "5m", "15m", "1h", "4h", "1d".
    - now: reference time; defaults to current UTC if None.
    - config: optional pre-loaded dict from load_timeframe_windows to avoid re-reading YAML.

    Behavior:
    - Uses lookback_days from the config to compute start = now - timedelta(days=lookback_days).
    - Returns (start, end) in UTC.
    - Raises KeyError if timeframe is unknown.
    """
    now = now or datetime.now(timezone.utc)
    cfg = config or load_timeframe_windows()

    if timeframe not in cfg:
        raise KeyError(f"Unknown timeframe: {timeframe}")

    tfw = cfg[timeframe]
    start = now - timedelta(days=tfw.lookback_days)
    return (start.astimezone(timezone.utc), now.astimezone(timezone.utc))
