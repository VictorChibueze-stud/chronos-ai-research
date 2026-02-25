"""Core feature engine for Chronos-AI (Phase 1).

Pure, deterministic functions that compute indicators and simple structure
features from OHLC candle data. This module is broker-agnostic and side-effect
free.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, Dict, Any, List, Optional, Iterable

import math
import numpy as np
import pandas as pd
from dateutil.parser import parse as parse_date


@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def _to_datetime(v) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.utcfromtimestamp(float(v))
    return parse_date(str(v))


def normalize_candles(data: Sequence[Dict[str, Any]]) -> List[Candle]:
    """Normalize various input formats into a chronological list of `Candle`.

    Accepts a sequence of dict-like objects with keys: 'timestamp' or 'epoch',
    and 'open','high','low','close', optional 'volume'. Returns a list sorted
    ascending by timestamp.
    """
    def _first_non_none(values: Iterable[Any]) -> Optional[Any]:
        for v in values:
            if v is not None:
                return v
        return None

    def _get_field(row: Any, keys: List[str], field_name: str, default: Optional[Any] = None) -> Any:
        # extract candidate values preserving explicit 0.0
        candidates: List[Any] = []
        for k in keys:
            if hasattr(row, "get"):
                candidates.append(row.get(k))
            else:
                try:
                    candidates.append(row[k] if k in row else None)
                except Exception:
                    candidates.append(None)
        val = _first_non_none(candidates)
        if val is None:
            if default is not None:
                return default
            raise ValueError(f"Missing '{field_name}' in row: {row}")
        return val

    candles: List[Candle] = []
    for row in data:
        if isinstance(row, Candle):
            candles.append(row)
            continue
        ts = None
        if hasattr(row, "get"):
            ts = _first_non_none([row.get("timestamp"), row.get("time"), row.get("epoch")])
        else:
            ts = row.get("timestamp") if "timestamp" in row else (row.get("time") if "time" in row else (row.get("epoch") if "epoch" in row else None))
        timestamp = _to_datetime(ts) if ts is not None else datetime.utcnow()

        o_val = _get_field(row, ["open", "o", "Open"], "open")
        h_val = _get_field(row, ["high", "h", "High"], "high")
        l_val = _get_field(row, ["low", "l", "Low"], "low")
        c_val = _get_field(row, ["close", "c", "Close"], "close")
        v_val = _get_field(row, ["volume", "vol", "Volume"], "volume", default=0.0)

        o = float(o_val)
        h = float(h_val)
        l = float(l_val)
        c = float(c_val)
        v = float(v_val)

        candles.append(Candle(timestamp=timestamp, open=o, high=h, low=l, close=c, volume=v))
    candles.sort(key=lambda x: x.timestamp)
    return candles


### Indicators (array-based helpers)


def sma(values: Sequence[float], n: int) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    if n <= 0:
        raise ValueError("n must be > 0")
    if a.size == 0:
        return a
    return pd.Series(a).rolling(window=n, min_periods=1).mean().to_numpy()


def ema(values: Sequence[float], n: int) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return a
    return pd.Series(a).ewm(span=n, adjust=False).mean().to_numpy()


def rma(values: Sequence[float], n: int) -> np.ndarray:
    # Wilder moving average (RMA)
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return a
    out = np.empty_like(a)
    alpha = 1.0 / n
    out[0] = a[0]
    for i in range(1, a.size):
        out[i] = (a[i] * alpha) + out[i - 1] * (1 - alpha)
    return out


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def stddev(values: Sequence[float], n: int) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return a
    return pd.Series(a).rolling(window=n, min_periods=1).std(ddof=0).to_numpy()


def rsi(closes: Sequence[float], n: int = 14) -> np.ndarray:
    a = np.asarray(closes, dtype=float)
    if a.size == 0:
        return a
    deltas = np.diff(a)
    ups = np.where(deltas > 0, deltas, 0.0)
    downs = np.where(deltas < 0, -deltas, 0.0)
    # pad to match length
    ups = np.concatenate(([0.0], ups))
    downs = np.concatenate(([0.0], downs))
    avg_up = rma(ups, n)
    avg_down = rma(downs, n)
    # compute RS safely avoiding divide-by-zero
    rs = np.empty_like(avg_up)
    mask_zero = avg_down == 0.0
    # for positions where denominator is non-zero
    nonzero_idx = ~mask_zero
    if np.any(nonzero_idx):
        rs[nonzero_idx] = avg_up[nonzero_idx] / avg_down[nonzero_idx]
    # for denominator zero: if numerator zero => rs=0, else rs=inf (will map to RSI=100)
    if np.any(mask_zero):
        rs[mask_zero] = np.where(avg_up[mask_zero] == 0.0, 0.0, np.inf)

    with np.errstate(divide="ignore", invalid="ignore"):
        rsi_arr = 100.0 - (100.0 / (1.0 + rs))

    # map infinities and NaNs to finite, sensible defaults
    rsi_arr = np.where(np.isinf(rs), 100.0, rsi_arr)
    rsi_arr = np.where(np.isnan(rsi_arr), 50.0, rsi_arr)
    return rsi_arr.astype(float)


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> np.ndarray:
    hs = np.asarray(highs, dtype=float)
    ls = np.asarray(lows, dtype=float)
    cs = np.asarray(closes, dtype=float)
    if hs.size == 0:
        return hs
    trs = np.empty_like(hs)
    prev_close = None
    for i in range(hs.size):
        trs[i] = true_range(hs[i], ls[i], prev_close)
        prev_close = cs[i]
    return rma(trs, n)


def atr_pct(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> np.ndarray:
    a = atr(highs, lows, closes, n=n)
    cs = np.asarray(closes, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(cs == 0, 0.0, a / cs)


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int = 14) -> np.ndarray:
    # Simplified ADX implementation
    hs = np.asarray(highs, dtype=float)
    ls = np.asarray(lows, dtype=float)
    cs = np.asarray(closes, dtype=float)
    if hs.size < 2:
        return np.array([])
    up_move = hs[1:] - hs[:-1]
    down_move = ls[:-1] - ls[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_list = np.empty(hs.size - 1)
    for i in range(1, hs.size):
        tr_list[i - 1] = true_range(hs[i], ls[i], cs[i - 1])
    # compute ATR over TRs safely
    atr_val = rma(np.concatenate(([tr_list[0]], tr_list)), n)
    atr_val = atr_val[1:]

    # smooth DM series
    plus_dm_s = rma(plus_dm, n)
    minus_dm_s = rma(minus_dm, n)

    # compute DI values safely using np.divide with where to avoid divide-by-zero
    plus_di = np.zeros_like(atr_val)
    minus_di = np.zeros_like(atr_val)
    nonzero_atr = atr_val != 0.0
    if np.any(nonzero_atr):
        plus_di[nonzero_atr] = 100.0 * (plus_dm_s[nonzero_atr] / atr_val[nonzero_atr])
        minus_di[nonzero_atr] = 100.0 * (minus_dm_s[nonzero_atr] / atr_val[nonzero_atr])

    # compute DX and ADX
    denom = plus_di + minus_di
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100.0 * (np.abs(plus_di - minus_di) / (denom + 1e-9))
    adx_arr = rma(dx, n)

    # pad to match original length and ensure finite output
    out = np.concatenate((np.full(hs.size - adx_arr.size, np.nan), adx_arr))
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return out.astype(float)


def bollinger_pct(closes: Sequence[float], n: int = 20, k: float = 2.0) -> np.ndarray:
    a = np.asarray(closes, dtype=float)
    ma = sma(a, n)
    sd = stddev(a, n)
    with np.errstate(invalid="ignore"):
        return (a - (ma - k * sd)) / (2 * k * sd)


def donchian_high_low(values: Sequence[float], n: int = 20) -> Dict[str, np.ndarray]:
    s = pd.Series(values)
    high = s.rolling(n, min_periods=1).max().to_numpy()
    low = s.rolling(n, min_periods=1).min().to_numpy()
    return {"high": high, "low": low}


### Structure detection (simplified / deterministic)


def detect_swings(
    highs: Sequence[float],
    lows: Sequence[float],
    lookback: int = 5,
    candles: Optional[List] = None,
    atr_arr: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """Detect local swing highs and lows.

    Returns a list of dicts, each with keys:
        type      : 'SH' (swing high) or 'SL' (swing low)
        price     : float – the high or low price at the swing
        index     : int   – position in the input arrays
        timestamp : datetime or None (populated when candles is supplied)
        strength  : float – ATR-normalised protrusion; 0.0 when atr_arr is None

    Post-processing guarantees:
        • Strictly alternating SH → SL → SH (same-type runs collapse to the
          more extreme member)
        • Proximity deduplication: same-type swings within lookback//2 bars
          are merged, keeping the more extreme price
    """
    hs = np.asarray(highs, dtype=float)
    ls = np.asarray(lows, dtype=float)
    n = hs.size
    w = max(1, lookback)  # fully respected — no cap
    raw: List[Dict[str, Any]] = []

    for i in range(w, n - w):
        lo, hi = i - w, i + w + 1
        window_hs = hs[lo:hi]
        window_ls = ls[lo:hi]

        has_atr = atr_arr is not None and i < len(atr_arr)
        atr_val = max(float(atr_arr[i]), 0.0001) if has_atr else None
        ts = candles[i].timestamp if (candles is not None and i < len(candles)) else None

        # --- Swing high ---
        max_h = float(window_hs.max())
        if hs[i] >= max_h:
            left_hs = hs[lo:i]
            # leftmost rule: reject if an earlier bar in the window ties the max
            if left_hs.size == 0 or float(left_hs.max()) < hs[i]:
                strength = (float(hs[i]) - float(window_ls.max())) / atr_val if has_atr else 0.0
                raw.append({
                    "type": "SH",
                    "price": float(hs[i]),
                    "index": int(i),
                    "timestamp": ts,
                    "strength": float(strength),
                })

        # --- Swing low ---
        min_l = float(window_ls.min())
        if ls[i] <= min_l:
            left_ls = ls[lo:i]
            if left_ls.size == 0 or float(left_ls.min()) > ls[i]:
                strength = (float(window_hs.min()) - float(ls[i])) / atr_val if has_atr else 0.0
                raw.append({
                    "type": "SL",
                    "price": float(ls[i]),
                    "index": int(i),
                    "timestamp": ts,
                    "strength": float(strength),
                })

    raw.sort(key=lambda s: s["index"])

    # --- Proximity deduplication ---
    # Merge same-type swings within lookback//2 bars, keeping the more extreme price.
    half = max(1, lookback // 2)
    deduped: List[Dict[str, Any]] = []
    for s in raw:
        if not deduped:
            deduped.append(s)
            continue
        prev = deduped[-1]
        if s["type"] == prev["type"] and s["index"] - prev["index"] <= half:
            keep = (
                (s["type"] == "SH" and s["price"] > prev["price"])
                or (s["type"] == "SL" and s["price"] < prev["price"])
            )
            if keep:
                deduped[-1] = s
        else:
            deduped.append(s)

    # --- Alternating constraint ---
    # Ensure strict SH → SL → SH alternation; collapse same-type runs to the
    # more extreme member.
    alternated: List[Dict[str, Any]] = []
    for s in deduped:
        if not alternated:
            alternated.append(s)
            continue
        prev = alternated[-1]
        if s["type"] != prev["type"]:
            alternated.append(s)
        else:
            keep = (
                (s["type"] == "SH" and s["price"] > prev["price"])
                or (s["type"] == "SL" and s["price"] < prev["price"])
            )
            if keep:
                alternated[-1] = s

    return alternated


def detect_bos_choch(closes: Sequence[float], highs: Sequence[float], lows: Sequence[float]) -> List[Dict[str, Any]]:
    """Detect simple Break Of Structure (BOS) events based on swing extrema.

    Very small, heuristic-based method: find swings and check for new highs/lows
    that exceed previous swing extremes.
    """
    swings = detect_swings(highs, lows, lookback=3)
    events: List[Dict[str, Any]] = []
    if len(swings) < 2:
        return events
    swings_sorted = sorted(swings, key=lambda s: s["index"])
    last_hh = None
    last_ll = None
    for s in swings_sorted:
        if s["type"] == "HH":
            if last_hh is None or s["price"] > last_hh["price"]:
                events.append({"type": "BOS", "direction": "bull", "index": s["index"], "level": s["price"]})
            last_hh = s
        elif s["type"] == "LL":
            if last_ll is None or s["price"] < last_ll["price"]:
                events.append({"type": "BOS", "direction": "bear", "index": s["index"], "level": s["price"]})
            last_ll = s
    return events


def detect_fvg(highs: Sequence[float], lows: Sequence[float]) -> List[Dict[str, Any]]:
    """Detect very simple Fair Value Gaps (FVG) as gaps between non-overlapping bars.

    Heuristic: if bar i-2 high < bar i low => bullish FVG between i-2 and i.
    """
    hs = np.asarray(highs, dtype=float)
    ls = np.asarray(lows, dtype=float)
    n = hs.size
    gaps: List[Dict[str, Any]] = []
    for i in range(2, n):
        if hs[i - 2] < ls[i]:
            gaps.append({"type": "bull", "start": i - 2, "end": i, "filled": False})
        if ls[i - 2] > hs[i]:
            gaps.append({"type": "bear", "start": i - 2, "end": i, "filled": False})
    return gaps


def detect_liquidity_sweeps(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], lookback: int = 60, tol: float = 0.0005) -> List[Dict[str, Any]]:
    """Detect price spikes beyond recent highs/lows by a small tolerance.

    Returns list of sweep events.
    """
    hs = np.asarray(highs, dtype=float)
    ls = np.asarray(lows, dtype=float)
    cs = np.asarray(closes, dtype=float)
    events: List[Dict[str, Any]] = []
    n = hs.size
    lb = min(lookback, n - 1)
    for i in range(1, n):
        start = max(0, i - lb)
        recent_high = hs[start:i].max() if i - start > 0 else hs[i]
        recent_low = ls[start:i].min() if i - start > 0 else ls[i]
        if hs[i] > recent_high * (1 + tol):
            events.append({"type": "liquidity_sweep", "direction": "up", "index": i, "level": float(hs[i])})
        if ls[i] < recent_low * (1 - tol):
            events.append({"type": "liquidity_sweep", "direction": "down", "index": i, "level": float(ls[i])})
    return events


def detect_order_block(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[Dict[str, Any]]:
    """Return candidate order block zones: simple heuristic using last BOS and prior range.

    Returns list of dicts: {start_index, end_index, low, high}
    """
    events = detect_bos_choch(closes, highs, lows)
    if not events:
        return []
    # take the last BOS and return a prior candle range as an order block
    last = events[-1]
    idx = max(0, last["index"] - 3)
    start = idx
    end = last["index"]
    low = float(min(lows[start:end + 1]))
    high = float(max(highs[start:end + 1]))
    return [{"start": start, "end": end, "low": low, "high": high}]


def compute_zigzag(
    swings: List[Dict[str, Any]],
    candles: Optional[List[Candle]] = None,
    atr_arr: Optional[np.ndarray] = None,
    min_leg_atr: float = 2.0,
) -> List[Dict[str, Any]]:
    """Filter and return zigzag pivots from an existing swing list.

    Since detect_swings() already guarantees strict alternation and proximity
    deduplication, compute_zigzag() returns the swings as-is unless ATR-based
    leg filtering is requested. When atr_arr is provided, small legs (below
    min_leg_atr * ATR at the leg endpoint) are automatically merged, keeping
    the more extreme price from the surrounding points.

    Args:
        swings: Output from detect_swings()
        candles: Optional list of Candle objects (used internally for coordinate mapping)
        atr_arr: Optional ATR array; if None, no leg filtering applied
        min_leg_atr: Minimum leg size as a multiple of ATR (default 2.0)

    Returns:
        List of zigzag dicts with keys: type, price, index, timestamp, strength.
        If atr_arr is None, returns swings unchanged. Otherwise, small legs are
        merged to reduce noise while preserving structure alternation.
    """
    if atr_arr is None or len(swings) < 2:
        return swings

    # Iteratively merge small legs
    filtered = list(swings)
    changed = True
    while changed and len(filtered) >= 2:
        changed = False
        merged: List[Dict[str, Any]] = []

        i = 0
        while i < len(filtered):
            if i == len(filtered) - 1:
                merged.append(filtered[i])
                i += 1
                continue

            current = filtered[i]
            next_point = filtered[i + 1]

            # Calculate leg size
            leg_size = abs(next_point["price"] - current["price"])

            # Get ATR at endpoint
            endpoint_idx = next_point["index"]
            if endpoint_idx >= len(atr_arr):
                # Index out of bounds, keep current
                merged.append(current)
                i += 1
                continue

            atr_val = max(float(atr_arr[endpoint_idx]), 0.0001)
            threshold = min_leg_atr * atr_val

            if leg_size < threshold:
                # Small leg: merge by removing next_point
                # Keep the more extreme price from current and lookahead
                if i + 2 < len(filtered):
                    # There's a point after next_point
                    lookahead = filtered[i + 2]
                    if current["type"] == "SH":
                        # For SH, keep the higher price
                        if lookahead["price"] > current["price"]:
                            # Update current to lookahead's price (more extreme up)
                            current = {
                                **current,
                                "price": lookahead["price"],
                                "index": lookahead["index"],
                                "timestamp": lookahead["timestamp"],
                            }
                        # Skip both next_point and lookahead in this iteration
                        merged.append(current)
                        i += 3
                        changed = True
                    else:  # SL
                        # For SL, keep the lower price
                        if lookahead["price"] < current["price"]:
                            # Update current to lookahead's price (more extreme down)
                            current = {
                                **current,
                                "price": lookahead["price"],
                                "index": lookahead["index"],
                                "timestamp": lookahead["timestamp"],
                            }
                        # Skip both next_point and lookahead in this iteration
                        merged.append(current)
                        i += 3
                        changed = True
                else:
                    # No lookahead, just keep current and next_point
                    merged.append(current)
                    i += 1
            else:
                # Leg size is OK, keep both
                merged.append(current)
                i += 1

        filtered = merged

    return filtered


def detect_bos_choch_from_zigzag(zigzag: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect Break Of Structure (BOS) and Change Of Character (CHOCH) from zigzag pivots.

    Uses a state machine: trend = "up" | "down" | "unknown".
    Trend is initialised from the first 3 zigzag points before any events are emitted:
      - rising pattern (zigzag[2].price > zigzag[0].price) -> trend = "up"
      - falling pattern                                     -> trend = "down"
      - otherwise                                           -> trend = "unknown"

    For each SH point:
      - trend=="up"   and price > last_sh.price -> BOS_UP,   update last_sh
      - trend=="down" and price > last_sh.price -> CHOCH_UP, trend="up", update last_sh
      - else                                    -> update last_sh silently

    For each SL point (mirror logic):
      - trend=="down" and price < last_sl.price -> BOS_DOWN,   update last_sl
      - trend=="up"   and price < last_sl.price -> CHOCH_DOWN, trend="down", update last_sl
      - else                                    -> update last_sl silently

    Args:
        zigzag: Strictly alternating list from compute_zigzag() / detect_swings().

    Returns:
        List of event dicts:
            {"type": "BOS_UP"|"BOS_DOWN"|"CHOCH_UP"|"CHOCH_DOWN",
             "price": float,      <- the structural level that was broken
             "index": int,        <- bar index of the breaking point
             "timestamp": datetime or None,
             "level": float}      <- same as price, for clarity in visualisation
    """
    if len(zigzag) < 2:
        return []

    # Initialise trend from the first 3 zigzag points
    trend: str = "unknown"
    if len(zigzag) >= 3:
        if zigzag[2]["price"] > zigzag[0]["price"]:
            trend = "up"
        elif zigzag[2]["price"] < zigzag[0]["price"]:
            trend = "down"

    events: List[Dict[str, Any]] = []
    last_sh: Optional[Dict[str, Any]] = None
    last_sl: Optional[Dict[str, Any]] = None

    for zpoint in zigzag:
        ptype = zpoint["type"]
        price = float(zpoint["price"])
        idx   = int(zpoint["index"])
        ts    = zpoint.get("timestamp")

        if ptype == "SH":
            if last_sh is not None and price > last_sh["price"]:
                if trend == "up":
                    events.append({
                        "type": "BOS_UP",
                        "price": float(last_sh["price"]),
                        "index": idx,
                        "timestamp": ts,
                        "level": float(last_sh["price"]),
                    })
                elif trend == "down":
                    events.append({
                        "type": "CHOCH_UP",
                        "price": float(last_sh["price"]),
                        "index": idx,
                        "timestamp": ts,
                        "level": float(last_sh["price"]),
                    })
                    trend = "up"
            last_sh = zpoint

        else:  # "SL"
            if last_sl is not None and price < last_sl["price"]:
                if trend == "down":
                    events.append({
                        "type": "BOS_DOWN",
                        "price": float(last_sl["price"]),
                        "index": idx,
                        "timestamp": ts,
                        "level": float(last_sl["price"]),
                    })
                elif trend == "up":
                    events.append({
                        "type": "CHOCH_DOWN",
                        "price": float(last_sl["price"]),
                        "index": idx,
                        "timestamp": ts,
                        "level": float(last_sl["price"]),
                    })
                    trend = "down"
            last_sl = zpoint

    return events


def compute_price_features(candles: List[Candle], timeframe: str, max_lookback: int = 500) -> Dict[str, Any]:
    """Compute a structured set of price features for a chronological list of candles.

    Returns a dictionary containing metadata, a 'now_panel' snapshot, regime tags,
    structure map, ict_events (BOS/CHOCH/FVG/sweeps/OB), and recent window stats.
    """
    # Per-timeframe configuration for zigzag minimum leg size (in ATR multiples)
    ZIGZAG_MIN_LEG_ATR = {
        "1m": 1.5,
        "5m": 2.0,
        "15m": 2.5,
        "1H": 3.0,
        "4H": 3.0,
        "D": 2.5,
        "1d": 2.5,
    }
    min_leg_atr_for_tf = ZIGZAG_MIN_LEG_ATR.get(timeframe, 2.0)
    if not candles:
        # Return a minimal, safe feature dictionary for empty input so callers
        # (notebooks, agents, tests) do not crash when provided empty data.
        return {
            "meta": {"timeframe": timeframe, "length": 0},
            "now_panel": {
                "time": "",
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0.0,
                # common keys used by downstream code
                "ema_fast": 0.0,
                "ema_slow": 0.0,
                "ema20": 0.0,
                "ema50": 0.0,
                "rsi": 50.0,
                "atr": 0.0,
                "atr14": 0.0,
                "adx": 0.0,
                "adx14": 0.0,
            },
            "regime_tags": {
                "is_trending_up": False,
                "is_trending_down": False,
                "is_range": True,
                "adx": 0.0,
                "is_vol_spike": False,
                "is_low_vol": True,
            },
            "structure_map": {
                "swing_highs": [],
                "swing_lows": [],
                "swings": [],
                "order_blocks": [],
                "fvg": [],
            },
            "ict_events": [],
            "recent_window": {"num_candles": 0, "close_mean": 0.0, "close_std": 0.0, "pct_up": 0.0},
        }
    # cap lookback
    candles = candles[-max_lookback:]
    times = [c.timestamp for c in candles]
    opens = [c.open for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    vols = [c.volume for c in candles]

    # Indicators
    close_arr = np.asarray(closes, dtype=float)
    ema20 = ema(close_arr, 20)
    ema50 = ema(close_arr, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, n=14)
    atrp = atr_pct(highs, lows, closes, n=14)
    adx14 = adx(highs, lows, closes, n=14)

    # Structure
    swings = detect_swings(highs, lows, lookback=5, candles=candles, atr_arr=atr14)
    swings = compute_zigzag(swings, candles=candles, atr_arr=atr14, min_leg_atr=min_leg_atr_for_tf)
    bos_events = detect_bos_choch(closes, highs, lows)
    fvg = detect_fvg(highs, lows)
    sweeps = detect_liquidity_sweeps(highs, lows, closes, lookback=min(60, len(candles) - 1))
    obs = detect_order_block(highs, lows, closes)

    # Regime tags heuristics
    is_trending_up = bool(ema20[-1] > ema50[-1])
    is_trending_down = bool(ema20[-1] < ema50[-1])
    is_range = not (is_trending_up or is_trending_down)
    vol_spike = bool(atrp[-1] > np.nanpercentile(atrp[~np.isnan(atrp)], 90) if np.any(~np.isnan(atrp)) else False)

    now_panel = {
        "time": times[-1].isoformat(),
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": closes[-1],
        "volume": vols[-1],
        "ema20": float(ema20[-1]) if ema20.size else None,
        "ema50": float(ema50[-1]) if ema50.size else None,
        "atr14": float(atr14[-1]) if atr14.size else None,
        "atr_pct": float(atrp[-1]) if atrp.size else None,
        "adx14": float(adx14[-1]) if adx14.size else None,
        "rsi": float(rsi14[-1]) if (isinstance(rsi14, np.ndarray) and rsi14.size) else 50.0,
    }

    recent_window = {
        "num_candles": len(candles),
        "close_mean": float(np.mean(close_arr)),
        "close_std": float(np.std(close_arr)),
        "pct_up": float(np.mean(np.diff(close_arr) > 0.0)),
    }

    swing_highs = [s for s in swings if s["type"] == "SH"]
    swing_lows = [s for s in swings if s["type"] == "SL"]
    structure_map = {
        "swings": swings,
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "order_blocks": obs,
        "fvg": fvg,
    }

    ict_events = bos_events + fvg + sweeps

    features = {
        "meta": {"timeframe": timeframe, "start": times[0].isoformat(), "end": times[-1].isoformat(), "num_candles": len(candles)},
        "now_panel": now_panel,
        "regime_tags": {"is_trending_up": is_trending_up, "is_trending_down": is_trending_down, "is_range": is_range, "is_vol_spike": vol_spike},
        "structure_map": structure_map,
        "ict_events": ict_events,
        "recent_window": recent_window,
    }
    return features
"""Stub module to be implemented in later phases."""
