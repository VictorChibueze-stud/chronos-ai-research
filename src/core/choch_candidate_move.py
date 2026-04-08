"""CHoCH candidate move: swing anchor in allowed band + reference BOS vs last close.

Pure helpers (no I/O). Used by GET /api/analysis to pick a pivot and evaluate structure_broken.
"""
from __future__ import annotations

from typing import Any


def union_zone_bounds(
    global_zone: dict[str, Any] | None,
    internal_zone: dict[str, Any] | None,
) -> tuple[float, float] | None:
    """Return (z_lo, z_hi) union of global and internal CHoCH rectangles, or None if neither."""
    lows: list[float] = []
    highs: list[float] = []
    for z in (global_zone, internal_zone):
        if not z:
            continue
        lo = z.get("lower_boundary")
        hi = z.get("upper_boundary")
        if lo is None or hi is None:
            continue
        lows.append(float(lo))
        highs.append(float(hi))
    if not lows:
        return None
    return min(lows), max(highs)


def pivot_low_price_allowed(price: float, z_lo: float, z_hi: float, impulse_floor: float) -> bool:
    """Uptrend: swing low inside union zone, or below zone down to impulse start (not below floor)."""
    if price > z_hi:
        return False
    if z_lo <= price <= z_hi:
        return True
    if price < z_lo:
        return price >= impulse_floor
    return False


def pivot_high_price_allowed(price: float, z_lo: float, z_hi: float, impulse_ceiling: float) -> bool:
    """Downtrend: swing high inside union zone, or above zone up to impulse start (not above ceiling)."""
    if price < z_lo:
        return False
    if z_lo <= price <= z_hi:
        return True
    if price > z_hi:
        return price <= impulse_ceiling
    return False


def last_confirmed_impulse_legs(legs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for leg in reversed(legs):
        if leg.get("type") == "impulse" and leg.get("confirmed"):
            return leg
    return None


def find_candidate_pivot_index(
    candles: list[Any],
    trend: str,
    global_zone: dict[str, Any] | None,
    internal_zone: dict[str, Any] | None,
    last_impulse: dict[str, Any],
    *,
    min_swing_candles: int = 3,
) -> int | None:
    """
    Deepest qualifying swing low (uptrend) or highest swing high (downtrend) in the allowed band;
    tie-break: latest bar index. Swing window matches ``trend_id._collect_candidates`` semantics.
    """
    if trend not in ("up", "down"):
        return None
    bounds = union_zone_bounds(global_zone, internal_zone)
    if bounds is None:
        return None
    z_lo, z_hi = bounds
    impulse_bound = float(last_impulse["start_price"])
    start_scan = int(last_impulse["start_index"]) + 1
    n = len(candles)
    m = min_swing_candles
    if n < 2 * m + 1:
        return None

    candidates: list[tuple[int, float]] = []
    for i in range(max(start_scan, m), n - m):
        window = candles[i - m : i + m + 1]
        if trend == "up":
            if candles[i].low != min(c.low for c in window):
                continue
            p = float(candles[i].low)
            if not pivot_low_price_allowed(p, z_lo, z_hi, impulse_bound):
                continue
            candidates.append((i, p))
        else:
            if candles[i].high != max(c.high for c in window):
                continue
            p = float(candles[i].high)
            if not pivot_high_price_allowed(p, z_lo, z_hi, impulse_bound):
                continue
            candidates.append((i, p))

    if not candidates:
        return None
    if trend == "up":
        best_p = min(c[1] for c in candidates)
        tied = [c for c in candidates if c[1] == best_p]
    else:
        best_p = max(c[1] for c in candidates)
        tied = [c for c in candidates if c[1] == best_p]
    return max(tied, key=lambda c: c[0])[0]


def reference_bos_before_pivot(
    legs: list[dict[str, Any]],
    pivot_index: int,
) -> tuple[float, int] | None:
    """BOS reference: end_price and end_index of the confirmed impulse with greatest end_index < pivot."""
    best_end = -1
    best: tuple[float, int] | None = None
    for leg in legs:
        if leg.get("type") != "impulse" or not leg.get("confirmed"):
            continue
        ei = leg.get("end_index")
        if ei is None:
            continue
        ei_int = int(ei)
        if ei_int >= pivot_index:
            continue
        ep = leg.get("end_price")
        if ep is None:
            continue
        if ei_int > best_end:
            best_end = ei_int
            best = (float(ep), ei_int)
    return best


def structure_broken_from_close(trend: str, last_close: float, reference_bos_price: float) -> bool:
    if trend == "up":
        return last_close > reference_bos_price
    if trend == "down":
        return last_close < reference_bos_price
    return False
