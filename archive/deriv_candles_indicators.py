from langflow.base.langchain_utilities.model import LCToolComponent
from langflow.io import MessageTextInput, Output, DropdownInput
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import json, websocket

WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={}"

SYMBOLS = {
    "Volatility 10 Index": "R_10",
    "Volatility 25 Index": "R_25",
    "Volatility 50 Index": "R_50",
    "Volatility 75 Index": "R_75",
    "Volatility 100 Index": "R_100",
    "Boom 300 Index": "BOOM300",
    "Boom 500 Index": "BOOM500",
    "Boom 1000 Index": "BOOM1000",
    "Crash 300 Index": "CRASH300",
    "Crash 500 Index": "CRASH500",
}

TF = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

class DerivCandlesIndicatorsV1(LCToolComponent):
    display_name = "Deriv Candles + Indicators"
    name = "DerivCandlesIndicatorsV1"
    description = "Fetch Deriv OHLC candles and technical/quant indicators"
    icon = "bar_chart"

    inputs = [
        MessageTextInput(name="api_token", display_name="Deriv API Token"),
        MessageTextInput(name="app_id", display_name="Deriv App ID", value="1089"),
        DropdownInput(name="symbol_name", display_name="Symbol",
                      value="Volatility 10 Index", options=list(SYMBOLS.keys())),
        DropdownInput(name="timeframe_label", display_name="Timeframe",
                      value="15m", options=list(TF.keys()), tool_mode=True),
        MessageTextInput(name="start_date", display_name="Start (ISO, required)",
                         value="2025-01-01", tool_mode=True),
        MessageTextInput(name="end_date", display_name="End (ISO, required)",
                         value="2025-08-01", tool_mode=True),
        MessageTextInput(name="base_url", display_name="Indicators API Base URL",
                         value="https://dev-obb.machinaai.net/api/v1"),
        MessageTextInput(name="api_username", display_name="Indicators API Username", value=""),
        MessageTextInput(name="api_password", display_name="Indicators API Password", value=""),
    ]
    outputs = [Output(display_name="Candles + Indicators", name="output", method="run")]

    def build_tool(self):
        from langflow.field_typing import Tool
        from typing import cast
        return cast("Tool", None)

    # ---- helpers ----
    @staticmethod
    def _to_epoch(iso_str: Optional[str]) -> int:
        if not iso_str:
            raise RuntimeError("Start/End ISO datetimes are required.")
        s = iso_str.strip()
        try:
            if "T" in s:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        except Exception:
            raise RuntimeError(f"Invalid ISO datetime: {iso_str}")
        return int(dt.timestamp())

    def _post_indicator(self, url: str, params: Dict[str, Any], series: List[Dict[str, Any]]):
        try:
            try:
                import requests
            except Exception:
                return {"ok": False, "err": "Missing 'requests' package. Install in container: pip install requests"}
            auth = (self.api_username, self.api_password) if self.api_username else None
            r = requests.post(url, params=params, json=series, timeout=60, auth=auth)
            if r.status_code == 200:
                try:
                    return {"ok": True, "data": r.json()}
                except Exception as e:
                    return {"ok": False, "err": f"JSON parse error: {e}"}
            return {"ok": False, "err": f"{r.status_code}: {r.text[:400]}"}
        except Exception as exc:
            return {"ok": False, "err": str(exc)}

    def run(self):
        try:
            # --- map inputs ---
            symbol = SYMBOLS[self.symbol_name]
            gran = TF[self.timeframe_label]
            start_ep = self._to_epoch(self.start_date)
            end_ep = self._to_epoch(self.end_date)
            if end_ep < start_ep:
                return {"status": "error", "error_message": "End date before start date."}

            # --- fetch OHLC from Deriv (date range only; no count) ---
            req = {"ticks_history": symbol, "style": "candles",
                   "granularity": gran, "start": start_ep, "end": end_ep}

            ws = websocket.create_connection(WS_URL.format(self.app_id))
            try:
                ws.send(json.dumps({"authorize": self.api_token})); _ = json.loads(ws.recv())
                ws.send(json.dumps(req))
                resp = {}
                while True:
                    msg = json.loads(ws.recv())
                    if "error" in msg or "candles" in msg:
                        resp = msg; break
            finally:
                ws.close()

            if "error" in resp:
                return {"status": "error", "request_sent": req, "deriv_error": resp["error"]}

            raw = resp.get("candles", [])
            series: List[Dict[str, Any]] = []
            for c in raw:
                ts = datetime.fromtimestamp(int(c["epoch"]), tz=timezone.utc)
                series.append({
                    "datetime": ts.isoformat(),   # primary timestamp (UTC)
                    "epoch": int(c["epoch"]),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                })

            # --- define indicator jobs INSIDE the class scope (no globals) ---
            TECH_JOBS: Dict[str, Dict[str, Any]] = {
                "/technical/rsi":   {"target": "close", "length": 14},
                "/technical/stoch": {"fast_k_period": 14, "slow_d_period": 3, "slow_k_period": 3},
                "/technical/cg":    {"target": "close", "length": 14},
                "/technical/fisher":{"length": 14},
                "/technical/sma":   {"target": "close", "length": 50},
                "/technical/ema":   {"target": "close", "length": 50},
                "/technical/wma":   {"target": "close", "length": 50},
                "/technical/hma":   {"target": "close", "length": 50},
                "/technical/zlma":  {"target": "close", "length": 20},
                "/technical/macd":  {"target": "close", "fast": 12, "slow": 26, "signal": 9},
                "/technical/adx":   {"length": 14},
                "/technical/aroon": {"length": 14},
                "/technical/cci":   {"length": 14},
                "/technical/ichimoku": {},
                "/technical/bbands": {"target": "close", "length": 20, "std": 2},
                "/technical/atr":    {"length": 14},
                "/technical/donchian": {"lower_length": 20, "upper_length": 20},
                "/technical/kc":     {"length": 20, "scalar": 2, "mamode": "ema"},
                "/technical/demark": {},
                "/technical/fib":    {},
                "/technical/clenow": {},
                "/technical/cones":  {"length": 20},
                # skipped: /obv, /ad, /adosc, /vwap (need volume)
            }
            QE_JOBS: Dict[str, Dict[str, Any]] = {
                "/quantitative/summary":                 {"target": "close"},
                "/quantitative/normality":               {"target": "close"},
                "/quantitative/unitroot_test":           {"target": "close"},
                "/quantitative/performance/omega_ratio": {"target": "close"},
                "/quantitative/performance/sharpe_ratio":{"target": "close"},
                "/quantitative/performance/sortino_ratio":{"target": "close"},
                "/econometrics/autocorrelation":         {"target": "close"},
                "/econometrics/unit_root":               {"target": "close"},
            }

            base = self.base_url.rstrip("/")
            strip = {"datetime","date","timestamp","epoch","open","high","low","close","volume"}

            # seed merged with datetime + close
            merged: Dict[str, Dict[str, Any]] = {row["datetime"]: {"datetime": row["datetime"], "close": row["close"]} for row in series}

            # technical indicators (per-row series)
            for ep, params in TECH_JOBS.items():
                res = self._post_indicator(f"{base}{ep}", params, series)
                if not res["ok"]:
                    merged[f"__error__{ep}"] = {"error": res["err"]}
                    continue
                payload = res["data"]
                rows = payload if isinstance(payload, list) else payload.get("results", [])
                for r in rows or []:
                    key = r.get("datetime") or r.get("date") or r.get("timestamp")
                    if not key:
                        continue
                    row = merged.get(key) or {"datetime": key}
                    for k, v in r.items():
                        if k not in strip:
                            row[k] = v
                    merged[key] = row

            # quantitative/econometrics (often summaries)
            qe_results = {}
            for ep, params in QE_JOBS.items():
                qe_results[ep] = self._post_indicator(f"{base}{ep}", params, series)

            # build aligned indicators time-series
            indicators = []
            for dt_key in sorted([k for k in merged.keys() if not k.startswith("__error__")]):
                row = merged[dt_key]
                if "datetime" in row and "close" in row:
                    indicators.append(row)

            return {
                "status": "ok",
                "symbol_name": self.symbol_name,
                "symbol": symbol,
                "timeframe": self.timeframe_label,
                "granularity_sec": gran,
                "request_sent": req,
                "series": series,        # OHLC
                "indicators": indicators,# per-bar: datetime, close, + indicator fields
                "qe_results": qe_results # endpoint responses (summaries/diagnostics)
            }

        except Exception as exc:
            return {"status": "error", "error_message": str(exc)}
