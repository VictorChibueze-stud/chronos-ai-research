"""Simple Agent Harness to collect market context and build prompts."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List

from src.adapters.deriv_data import fetch_deriv_ohlc
from src.core.features import compute_price_features, Candle
from src.llm.context import build_multi_snapshot
from src.agent.prompts import SYSTEM_PROMPT_V1


class AgentHarness:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def _tf_to_seconds(self, tf: str) -> int:
        tf = tf.strip().lower()
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        # default minutes
        return int(tf) * 60

    def collect_context(self) -> str:
        """Collect features for D1, 4H, 1H and return JSON string of snapshots."""
        end = datetime.utcnow()
        start = end - timedelta(days=5)
        timeframes = ["D1", "4H", "1H"]
        candles_map: Dict[str, List[Candle]] = {}

        for tf in timeframes:
            try:
                gran = self._tf_to_seconds(tf)
                candles: List[Candle] = fetch_deriv_ohlc(self.symbol, gran, start, end)
                if not candles:
                    # provide minimal fallback: create one synthetic candle
                    now = datetime.utcnow()
                    candles = [Candle(timestamp=now, open=1.0, high=1.1, low=0.9, close=1.05, volume=0.0)]
                candles_map[tf] = candles
            except Exception:
                # on failure, return an empty list for that timeframe
                candles_map[tf] = []

        # build_multi_snapshot now accepts a single dict mapping timeframes to candles
        multi = build_multi_snapshot(candles_map)
        # convert pydantic models to serializable dicts if needed
        snapshots = {tf: snap.dict() if hasattr(snap, "dict") else snap for tf, snap in multi.items()}
        out = {"symbol": self.symbol, "snapshots": snapshots}
        return json.dumps(out)

    def generate_prompt(self) -> str:
        ctx = self.collect_context()
        prompt = SYSTEM_PROMPT_V1 + "\nCURRENT MARKET DATA:\n" + ctx
        return prompt


if __name__ == "__main__":
    h = AgentHarness("R_10")
    print(h.generate_prompt())
