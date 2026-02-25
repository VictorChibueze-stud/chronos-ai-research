"""Local CSV OHLC loader returning `Candle` objects.

Utility to read CSV files with OHLC data and convert them into the
`Candle` dataclass used by the core feature engine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

import pandas as pd

from src.core.features import Candle, normalize_candles


def load_ohlc_from_csv(
	path: Union[str, Path],
	*,
	timestamp_col: str = "timestamp",
	open_col: str = "open",
	high_col: str = "high",
	low_col: str = "low",
	close_col: str = "close",
	volume_col: str = "volume",
) -> List[Candle]:
	"""Load OHLC data from a CSV file into a list of Candle objects.

	The CSV must contain at least: timestamp, open, high, low, close.
	Volume is optional and will be filled with 0.0 if missing.
	"""
	path = Path(path)
	if not path.exists():
		raise FileNotFoundError(f"CSV file not found: {path}")

	df = pd.read_csv(path)

	required = {timestamp_col, open_col, high_col, low_col, close_col}
	missing = [c for c in required if c not in df.columns]
	if missing:
		raise ValueError(f"Missing required OHLC columns in CSV: {missing}")

	if volume_col not in df.columns:
		df[volume_col] = 0.0

	records: List[Dict[str, Any]] = df.to_dict(orient="records")
	candles = normalize_candles(records)
	return candles

