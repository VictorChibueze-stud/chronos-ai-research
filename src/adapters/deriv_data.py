"""Deriv data adapter: fetch OHLC via Deriv WebSocket (read-only helpers).

This module provides a small helper to fetch historical OHLC/candles from
Deriv's WebSocket API and return `Candle` objects usable by the core feature
engine. Tests should monkeypatch `websocket.create_connection` to avoid
network calls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import websocket
from dateutil import parser as date_parser

from src.core.features import Candle, normalize_candles


@dataclass
class DerivConfig:
	app_id: str
	api_token: str

	@classmethod
	def from_env(cls, app_id_var: str = "DERIV_APP_ID", token_var: str = "DERIV_API_TOKEN") -> "DerivConfig":
		app_id = os.getenv(app_id_var)
		api_token = os.getenv(token_var)
		if not app_id or not api_token:
			raise RuntimeError(
				f"Missing Deriv credentials: ensure {app_id_var} and {token_var} are set in the environment or .env."
			)
		return cls(app_id=app_id, api_token=api_token)


def _to_epoch_seconds(dt: Any) -> int:
	if isinstance(dt, (int, float)):
		return int(dt)
	if isinstance(dt, datetime):
		if dt.tzinfo is None:
			dt = dt.replace(tzinfo=timezone.utc)
		return int(dt.timestamp())
	parsed = date_parser.parse(str(dt))
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=timezone.utc)
	return int(parsed.timestamp())


DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"


def fetch_deriv_ohlc(
	symbol_code: str,
	granularity_sec: int,
	start: Any,
	end: Any,
	*,
	cfg: Optional[DerivConfig] = None,
) -> List[Candle]:
	"""Fetch OHLC candles from Deriv via WebSocket and return a list of Candle objects.

	- symbol_code: e.g. "R_10", "R_25".
	- granularity_sec: seconds per candle (e.g., 300, 900).
	- start, end: datetime/ISO string/epoch (inclusive window).
	- cfg: optional DerivConfig; if None, read from env using DerivConfig.from_env().
	"""
	if cfg is None:
		cfg = DerivConfig.from_env()

	start_epoch = _to_epoch_seconds(start)
	end_epoch = _to_epoch_seconds(end)
	if end_epoch <= start_epoch:
		raise ValueError("end must be strictly greater than start for Deriv OHLC fetch.")

	url = DERIV_WS_URL.format(app_id=cfg.app_id)
	ws = websocket.create_connection(url, timeout=30)

	try:
		# authorize
		auth_payload = {"authorize": cfg.api_token}
		ws.send(json.dumps(auth_payload))
		auth_resp = json.loads(ws.recv())
		if "error" in auth_resp:
			raise RuntimeError(f"Deriv authorization error: {auth_resp['error']}")

		# request candles
		req = {
			"ticks_history": symbol_code,
			"style": "candles",
			"granularity": granularity_sec,
			"start": start_epoch,
			"end": end_epoch,
		}
		ws.send(json.dumps(req))

		resp: Dict[str, Any] = {}
		while True:
			msg = json.loads(ws.recv())
			if "error" in msg:
				raise RuntimeError(f"Deriv OHLC error: {msg['error']}")
			if "candles" in msg:
				resp = msg
				break

		raw_candles: Sequence[Dict[str, Any]] = resp.get("candles", [])
		if not raw_candles:
			return []

		rows: List[Dict[str, Any]] = []
		for c in raw_candles:
			rows.append(
				{
					"epoch": c.get("epoch"),
					"open": c.get("open"),
					"high": c.get("high"),
					"low": c.get("low"),
					"close": c.get("close"),
					"volume": c.get("volume", 0.0),
				}
			)

		candles = normalize_candles(rows)
		return candles

	finally:
		try:
			ws.close()
		except Exception:
			pass

