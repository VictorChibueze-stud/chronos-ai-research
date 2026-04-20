"""Compute and persist reference global structure (daily vs weekly) per symbol."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.cache import candle_store
from src.cache.candle_store import CandleDataError
from src.core.choch_zone import get_active_choch_zone
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.structure_levels import compute_all_structure_levels, compute_internal_structure_levels
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.choch_candidate_move import structure_broken_from_close
from src.core.trend_id import compute_internal_structure, identify_trend
from src.db.models import (
    CandidateImpulseCache,
    GlobalStructureCache,
    MonitoredSetup,
    PrimeImpulseStructure,
    SymbolAnalysisParams,
    StoredWalkerResult,
)

logger = logging.getLogger(__name__)

TIMEFRAME_LADDER = ["1mo", "1w", "1d", "4h", "1h", "30m", "15m", "5m"]

WALKER_CANDIDATE_TFS = ["4h", "1h", "30m"]
WALKER_DEEPENING_TFS = ["4h", "1h", "30m"]
WALKER_MAX_DEPTH = 3


def _resolve_filter_config(symbol: str, db: Session) -> dict:
    row = db.query(SymbolAnalysisParams).filter(
        SymbolAnalysisParams.symbol == symbol
    ).first()
    base = dict(SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
    if row and row.params_json:
        for key in base:
            if key in row.params_json and row.params_json[key] is not None:
                base[key] = row.params_json[key]
    return base


def _timeframes_below(reference_tf: str, count: int = 3) -> list[str]:
    ref = reference_tf.strip().lower()
    try:
        i = TIMEFRAME_LADDER.index(ref)
    except ValueError:
        return []
    return [
        TIMEFRAME_LADDER[j]
        for j in range(i + 1, min(i + 1 + count, len(TIMEFRAME_LADDER)))
    ]


def _reference_tf_to_ladder_key(gsc: GlobalStructureCache) -> str:
    rt = (gsc.reference_timeframe or "").strip().lower()
    if rt == "weekly":
        return "1w"
    if rt == "daily":
        return "1d"
    if rt in TIMEFRAME_LADDER:
        return rt
    return "1d"


def _parse_ts_json(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _candle_ts_utc(c: Any) -> datetime | None:
    ts = getattr(c, "timestamp", None)
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _candles_in_closed_interval(
    candles: list,
    t_start: datetime,
    t_end: datetime,
) -> list:
    if t_start.tzinfo is None:
        t_start = t_start.replace(tzinfo=timezone.utc)
    if t_end.tzinfo is None:
        t_end = t_end.replace(tzinfo=timezone.utc)
    out: list = []
    for c in candles:
        ct = _candle_ts_utc(c)
        if ct is None:
            continue
        if t_start <= ct <= t_end:
            out.append(c)
    return out


def _last_confirmed_impulse_leg(legs_json: list[Any] | None) -> dict[str, Any] | None:
    for leg in reversed(legs_json or []):
        if not isinstance(leg, dict):
            continue
        if leg.get("type") == "impulse" and leg.get("confirmed"):
            return leg
    return None


def _last_confirmed_retracement_leg(legs_json: list[Any] | None) -> dict[str, Any] | None:
    for leg in reversed(legs_json or []):
        if not isinstance(leg, dict):
            continue
        if leg.get("type") == "retracement" and leg.get("confirmed"):
            return leg
    return None


def _tf_ladder_index(tf: str) -> int:
    key = tf.strip().lower()
    try:
        return TIMEFRAME_LADDER.index(key)
    except ValueError:
        return -1


def _confirmed_leg_count(legs: list[dict[str, Any]] | None) -> int:
    if not legs:
        return 0
    return sum(1 for leg in legs if leg.get("confirmed"))


def _latest_zone_touch_index(
    candles: list,
    trend: str,
    zone: dict[str, Any] | None,
    lookback: int = 100,
) -> int | None:
    if not candles or trend not in ("up", "down") or not isinstance(zone, dict):
        return None
    lo = zone.get("lower_boundary")
    hi = zone.get("upper_boundary")
    if lo is None or hi is None:
        return None
    try:
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None

    start = max(0, len(candles) - lookback)
    for idx in range(len(candles) - 1, start - 1, -1):
        c = candles[idx]
        if trend == "up":
            if float(c.low) <= hi_f:
                return idx
        else:
            if float(c.high) >= lo_f:
                return idx
    return None


def _candidate_start_index_from_touch(
    candles: list,
    trend: str,
    zone: dict[str, Any],
    touch_idx: int,
) -> int:
    if trend not in ("up", "down"):
        return touch_idx
    lo = float(zone["lower_boundary"])
    hi = float(zone["upper_boundary"])

    best_idx = touch_idx
    if trend == "up":
        best_val = float(candles[touch_idx].low)
        for i in range(touch_idx, len(candles)):
            cv = float(candles[i].low)
            if cv <= hi and cv <= best_val:
                best_val = cv
                best_idx = i
    else:
        best_val = float(candles[touch_idx].high)
        for i in range(touch_idx, len(candles)):
            cv = float(candles[i].high)
            if cv >= lo and cv >= best_val:
                best_val = cv
                best_idx = i
    return best_idx


def _largest_confirmed_impulse_leg(legs: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_move = -1.0
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        if not leg.get("confirmed") or leg.get("type") != "impulse":
            continue
        if leg.get("start_price") is None or leg.get("end_price") is None:
            continue
        try:
            move = abs(float(leg["end_price"]) - float(leg["start_price"]))
        except (TypeError, ValueError):
            continue
        if move > best_move:
            best_move = move
            best = leg
    return best


def _json_safe(value: Any) -> Any:
    """Ensure value is JSON-serializable for ORM JSON columns."""
    return json.loads(json.dumps(value, default=str))


def _fetch_candles_safe(symbol_upper: str, timeframe: str, db: Session) -> list:
    try:
        return candle_store.get_candles(symbol_upper, timeframe, db)
    except CandleDataError as exc:
        logger.warning(
            "global_structure candle fetch failed symbol=%s tf=%s: %s",
            symbol_upper,
            timeframe,
            exc,
        )
        return []


def _apply_bos_break_confirmation(
    result: dict,
    candles: list,
    symbol: str,
) -> dict:
    """
    Post-process identify_trend output.
    If the last leg is an unconfirmed impulse and price has
    broken and sustained above/below the prior confirmed BOS level,
    mark it confirmed with the latest candle as rolling endpoint.
    """
    legs = result.get("legs", [])
    if not legs:
        return result

    last_leg = legs[-1]
    if last_leg.get("confirmed") or last_leg.get("type") != "impulse":
        return result

    confirmed_impulses = [
        l for l in legs
        if l.get("type") == "impulse"
        and l.get("confirmed")
        and l.get("end_price") is not None
    ]
    if not confirmed_impulses:
        return result

    bos_price = float(confirmed_impulses[-1]["end_price"])
    trend = result.get("trend")
    if not candles:
        return result

    last_candle = candles[-1]
    last_close = float(last_candle.close)
    bos_broken = (
        (trend == "up" and last_close > bos_price)
        or (trend == "down" and last_close < bos_price)
    )
    if not bos_broken:
        return result

    try:
        start_price = float(last_leg["start_price"])
        start_index = int(last_leg["start_index"])
    except (KeyError, TypeError, ValueError):
        return result

    end_index = len(candles) - 1
    last_leg["confirmed"] = True
    last_leg["end_price"] = last_close
    last_leg["end_index"] = end_index
    last_leg["end_timestamp"] = last_candle.timestamp
    last_leg["slope"] = (last_close - start_price) / max(1, end_index - start_index)
    last_leg["bos_break_confirmed"] = True
    last_leg["rolling_endpoint"] = True

    logger.info(
        "BOS-break confirmation: %s trend=%s bos=%.5f current=%.5f "
        "- developing impulse confirmed with rolling endpoint",
        symbol,
        trend,
        bos_price,
        last_close,
    )

    result["current_phase"] = "impulse"
    return result


def _enrich_legs_with_internal_structure(
    symbol: str,
    reference_tf: str,
    candles: list,
    legs: list[dict[str, Any]],
    db: Session,
    filter_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Enrich confirmed global impulse legs with deepened internal structure.
    For each confirmed impulse leg, scan progressively finer timeframes and
    attach the richest internal structure found.
    """
    if not candles or not legs:
        return legs

    try_tfs = [reference_tf] + _timeframes_below(reference_tf, len(TIMEFRAME_LADDER))
    tf_candles: dict[str, list] = {reference_tf: candles}

    for leg in legs:
        if not isinstance(leg, dict):
            continue
        if leg.get("type") != "impulse" or not leg.get("confirmed"):
            continue

        t0 = _parse_ts_json(leg.get("start_timestamp"))
        t1 = _parse_ts_json(leg.get("end_timestamp"))
        if t0 is None or t1 is None:
            si = leg.get("start_index")
            ei = leg.get("end_index")
            try:
                si_i = int(si)
                ei_i = int(ei)
                if si_i < 0 or ei_i < si_i or ei_i >= len(candles):
                    continue
            except (TypeError, ValueError):
                continue
            t0 = _candle_ts_utc(candles[si_i])
            t1 = _candle_ts_utc(candles[ei_i])
            if t0 is None or t1 is None:
                continue

        best_internal: dict[str, Any] | None = None
        best_tf = reference_tf
        best_confirmed = -1

        for tf in try_tfs:
            if tf not in tf_candles:
                tf_candles[tf] = _fetch_candles_safe(symbol, tf, db)
            tf_all = tf_candles[tf]
            tf_slice = _candles_in_closed_interval(tf_all, t0, t1)
            if len(tf_slice) < 10:
                continue

            try:
                result = identify_trend(tf_slice, **filter_config)
                if result.get("trend") == "range":
                    result = identify_trend(
                        tf_slice,
                        trend_confirmation_pct=0.005,
                        **{k: v for k, v in filter_config.items() if k != "trend_confirmation_pct"},
                    )
                compute_internal_structure(
                    tf_slice,
                    result["legs"],
                    trend_confirmation_pct=0.005,
                    **{k: v for k, v in filter_config.items() if k != "trend_confirmation_pct"},
                )
                confirmed = _confirmed_leg_count(result.get("legs"))
            except Exception as exc:
                logger.warning(
                    "global leg deepening failed symbol=%s tf=%s: %s",
                    symbol,
                    tf,
                    exc,
                )
                continue

            if confirmed > best_confirmed:
                best_confirmed = confirmed
                best_internal = _json_safe(result)
                best_tf = tf

            if confirmed >= 3:
                break

        if best_internal is not None:
            leg["internal_structure"] = best_internal
            leg["internal_tf_used"] = best_tf

    return legs


def compute_global_structure_for_symbol(
    symbol: str,
    db: Session,
) -> GlobalStructureCache | None:
    """
    Pick daily vs weekly identify_trend result by confirmed leg count (weekly wins ties),
    compute BOS / CHoCH / active zone, upsert GlobalStructureCache, commit, return row.
    """
    sym = symbol.strip().upper()
    filter_config = _resolve_filter_config(sym, db)
    daily_candles = _fetch_candles_safe(sym, "1d", db)
    weekly_candles = _fetch_candles_safe(sym, "1w", db)

    if not daily_candles and not weekly_candles:
        raise ValueError(f"No candle data available for {sym} on 1d or 1w")

    existing_row = (
        db.query(GlobalStructureCache)
        .filter(GlobalStructureCache.symbol == sym)
        .one_or_none()
    )

    daily_result = identify_trend(daily_candles, **filter_config)
    weekly_result = identify_trend(weekly_candles, **filter_config)

    dc = _confirmed_leg_count(daily_result.get("legs"))
    wc = _confirmed_leg_count(weekly_result.get("legs"))

    if wc > dc:
        reference_tf = "weekly"
        winning_candles = weekly_candles
        winning_result = weekly_result
    elif dc > wc:
        reference_tf = "daily"
        winning_candles = daily_candles
        winning_result = daily_result
    elif weekly_candles:
        reference_tf = "weekly"
        winning_candles = weekly_candles
        winning_result = weekly_result
    else:
        reference_tf = "daily"
        winning_candles = daily_candles
        winning_result = daily_result

    if not winning_candles:
        raise ValueError(f"No candles for selected reference timeframe for {sym}")

    new_result = winning_result

    if existing_row is not None:
        existing_legs = existing_row.legs_json or []
        had_rolling = any(
            l.get("rolling_endpoint") and l.get("confirmed") and l.get("bos_break_confirmed")
            for l in existing_legs
            if isinstance(l, dict)
        )
        if had_rolling:
            non_rolling_confirmed_impulses = [
                l for l in existing_legs
                if isinstance(l, dict)
                and l.get("type") == "impulse"
                and l.get("confirmed")
                and not l.get("rolling_endpoint")
                and l.get("end_price") is not None
            ]
            if non_rolling_confirmed_impulses:
                old_bos = float(non_rolling_confirmed_impulses[-1]["end_price"])
                new_last_close = float(winning_candles[-1].close) if winning_candles else 0.0
                trend_for_check = existing_row.trend_direction
                false_break = (
                    (trend_for_check == "up" and new_last_close < old_bos)
                    or (trend_for_check == "down" and new_last_close > old_bos)
                )
                if false_break:
                    logger.warning(
                        "FALSE BREAK detected: %s trend=%s "
                        "rolling impulse end=%.5f current=%.5f "
                        "- reverting to unconfirmed",
                        sym,
                        trend_for_check,
                        old_bos,
                        new_last_close,
                    )

    new_result = _apply_bos_break_confirmation(new_result, winning_candles, sym)

    legs_raw = new_result.get("legs") or []
    if isinstance(legs_raw, list) and legs_raw:
        reference_key = "1w" if reference_tf == "weekly" else "1d"
        legs_raw = _enrich_legs_with_internal_structure(
            sym,
            reference_key,
            winning_candles,
            legs_raw,
            db,
            filter_config,
        )
    trend = str(new_result.get("trend") or "range")

    levels = compute_all_structure_levels(winning_candles, legs_raw, trend)
    bos_raw = levels.get("bos_levels") or []
    choch_level = levels.get("choch_level")

    choch_zone_json: dict[str, Any] | None = None
    if trend in ("up", "down") and legs_raw:
        legs_for_zone = copy.deepcopy(legs_raw)
        active = get_active_choch_zone(legs_for_zone, trend, winning_candles)
        if active and active.get("choch_zone") is not None:
            choch_zone_json = _json_safe(active["choch_zone"])

    confirmed = _confirmed_leg_count(legs_raw)
    now = datetime.now(timezone.utc)
    start_ts = winning_candles[0].timestamp
    end_ts = winning_candles[-1].timestamp
    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)

    row = existing_row
    payload = {
        "reference_timeframe": reference_tf,
        "confirmed_leg_count": confirmed,
        "legs_json": _json_safe(legs_raw),
        "bos_levels_json": _json_safe(bos_raw),
        "choch_zone_json": choch_zone_json,
        "choch_level_json": _json_safe(choch_level) if choch_level is not None else None,
        "trend_direction": trend,
        "computed_at": now,
        "candle_start_timestamp": start_ts,
        "candle_end_timestamp": end_ts,
    }

    if row is None:
        row = GlobalStructureCache(symbol=sym, **payload)
        db.add(row)
    else:
        for key, val in payload.items():
            setattr(row, key, val)

    db.commit()
    db.refresh(row)
    return row


def compute_global_structure_all(db: Session) -> dict[str, int]:
    """
    Run compute_global_structure_for_symbol for each distinct MonitoredSetup.symbol.
    Logs per-symbol failures; returns success/failure/total counts.
    """
    symbols = (
        db.query(MonitoredSetup.symbol).distinct().order_by(MonitoredSetup.symbol.asc()).all()
    )
    success = 0
    failure = 0
    for (sym,) in symbols:
        if not sym:
            continue
        try:
            compute_global_structure_for_symbol(sym, db)
            success += 1
            logger.info("global_structure ok symbol=%s", sym)
        except Exception:
            failure += 1
            logger.exception("global_structure failed symbol=%s", sym)
    total = success + failure
    logger.info(
        "global_structure batch done success=%s failure=%s total=%s",
        success,
        failure,
        total,
    )
    return {"success": success, "failure": failure, "total": total}


def get_stored_global_structure(symbol: str, db: Session) -> GlobalStructureCache | None:
    """Return cached GlobalStructureCache row for symbol, or None."""
    sym = symbol.strip().upper()
    return (
        db.query(GlobalStructureCache)
        .filter(GlobalStructureCache.symbol == sym)
        .one_or_none()
    )


def compute_prime_impulse_structure(
    symbol: str,
    db: Session,
) -> PrimeImpulseStructure:
    """
    Pick the finest of three timeframes below global reference with the richest
    identify_trend on candles inside the last confirmed global impulse window.
    """
    sym = symbol.strip().upper()
    filter_config = _resolve_filter_config(sym, db)
    gsc = get_stored_global_structure(sym, db)
    if gsc is None:
        raise ValueError(f"No GlobalStructureCache row for {sym}")

    ladder_ref = _reference_tf_to_ladder_key(gsc)
    impulse = _last_confirmed_impulse_leg(gsc.legs_json)
    if impulse is None:
        raise ValueError(f"No confirmed impulse leg in global cache for {sym}")

    t0 = _parse_ts_json(impulse.get("start_timestamp"))
    t1 = _parse_ts_json(impulse.get("end_timestamp"))
    if t0 is None or t1 is None:
        raise ValueError(f"Impulse leg missing timestamps for {sym}")

    try:
        sp = float(impulse["start_price"])
        ep = float(impulse["end_price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Impulse leg missing prices for {sym}") from exc

    candidates: list[tuple[str, int, dict[str, Any], list]] = []
    for tf in _timeframes_below(ladder_ref, 3):
        all_c = _fetch_candles_safe(sym, tf, db)
        slice_c = _candles_in_closed_interval(all_c, t0, t1)
        if len(slice_c) < 10:
            continue
        sub = identify_trend(slice_c, **filter_config)
        cnt = _confirmed_leg_count(sub.get("legs"))
        candidates.append((tf, cnt, sub, slice_c))

    if not candidates:
        raise ValueError(f"No timeframe slice with enough candles for prime impulse {sym}")

    pool = [c for c in candidates if c[1] >= 3]
    if not pool:
        pool = candidates

    def _sort_key(x: tuple[str, int, dict[str, Any], list]) -> tuple[int, int]:
        tf, cnt, _, _ = x
        return (cnt, TIMEFRAME_LADDER.index(tf))

    win_tf, _win_cnt, sub, slice_c = max(pool, key=_sort_key)
    trend = str(sub.get("trend") or "range")
    legs_raw = sub.get("legs") or []

    levels = compute_all_structure_levels(slice_c, legs_raw, trend)
    bos_raw = levels.get("bos_levels") or []

    choch_zone_json: dict[str, Any] | None = None
    if trend in ("up", "down") and legs_raw:
        legs_for_zone = copy.deepcopy(legs_raw)
        active = get_active_choch_zone(legs_for_zone, trend, slice_c)
        if active and active.get("choch_zone") is not None:
            choch_zone_json = _json_safe(active["choch_zone"])

    now = datetime.now(timezone.utc)
    confirmed = _confirmed_leg_count(legs_raw)

    row = db.query(PrimeImpulseStructure).filter(PrimeImpulseStructure.symbol == sym).one_or_none()
    payload = {
        "source_timeframe": win_tf,
        "confirmed_leg_count": confirmed,
        "legs_json": _json_safe(legs_raw),
        "bos_levels_json": _json_safe(bos_raw),
        "choch_zone_json": choch_zone_json,
        "impulse_start_timestamp": t0,
        "impulse_end_timestamp": t1,
        "impulse_start_price": sp,
        "impulse_end_price": ep,
        "computed_at": now,
    }

    if row is None:
        row = PrimeImpulseStructure(symbol=sym, **payload)
        db.add(row)
    else:
        for key, val in payload.items():
            setattr(row, key, val)

    db.commit()
    db.refresh(row)
    return row


def compute_prime_impulse_structure_all(db: Session) -> dict[str, int]:
    symbols = (
        db.query(MonitoredSetup.symbol).distinct().order_by(MonitoredSetup.symbol.asc()).all()
    )
    success = 0
    failure = 0
    for (sym,) in symbols:
        if not sym:
            continue
        try:
            compute_prime_impulse_structure(sym, db)
            success += 1
            logger.info("prime_impulse_structure ok symbol=%s", sym)
        except Exception:
            failure += 1
            logger.exception("prime_impulse_structure failed symbol=%s", sym)
    total = success + failure
    logger.info(
        "prime_impulse_structure batch done success=%s failure=%s total=%s",
        success,
        failure,
        total,
    )
    return {"success": success, "failure": failure, "total": total}


def get_stored_prime_impulse_structure(symbol: str, db: Session) -> PrimeImpulseStructure | None:
    sym = symbol.strip().upper()
    return (
        db.query(PrimeImpulseStructure)
        .filter(PrimeImpulseStructure.symbol == sym)
        .one_or_none()
    )


def get_stored_candidate_impulse(symbol: str, db: Session) -> CandidateImpulseCache | None:
    sym = symbol.strip().upper()
    return (
        db.query(CandidateImpulseCache)
        .filter(CandidateImpulseCache.symbol == sym)
        .one_or_none()
    )


def compute_candidate_impulse_for_symbol(
    symbol: str,
    db: Session,
) -> CandidateImpulseCache | None:
    sym = symbol.strip().upper()
    gsc = get_stored_global_structure(sym, db)
    if gsc is None:
        return None
    pis = get_stored_prime_impulse_structure(sym, db)
    if pis is None:
        return None

    source_tf = _reference_tf_to_ladder_key(gsc)
    candles = _fetch_candles_safe(sym, source_tf, db)
    if not candles:
        return None

    trend = str(gsc.trend_direction or "range").lower()
    if trend not in ("up", "down"):
        return None

    current_price = float(candles[-1].close)
    global_zone = gsc.choch_zone_json if isinstance(gsc.choch_zone_json, dict) else None
    prime_zone = pis.choch_zone_json if isinstance(pis.choch_zone_json, dict) else None

    global_touch_idx = _latest_zone_touch_index(candles, trend, global_zone, lookback=200)
    prime_touch_idx = _latest_zone_touch_index(candles, trend, prime_zone, lookback=200)

    global_tested = global_touch_idx is not None
    prime_tested = prime_touch_idx is not None
    if not global_tested and not prime_tested:
        return None

    if global_tested and prime_tested:
        choch_source = "both"
    elif global_tested:
        choch_source = "global"
    else:
        choch_source = "prime_internal"

    start_timestamp: datetime | None = None
    retr = _last_confirmed_retracement_leg(gsc.legs_json)
    if retr is not None:
        start_timestamp = _parse_ts_json(retr.get("end_timestamp"))

    if start_timestamp is None:
        last_impulse = _last_confirmed_impulse_leg(gsc.legs_json)
        if last_impulse is not None:
            start_timestamp = _parse_ts_json(last_impulse.get("start_timestamp"))

    if start_timestamp is None:
        return None

    end_timestamp = candles[-1].timestamp
    if start_timestamp.tzinfo is None:
        start_timestamp = start_timestamp.replace(tzinfo=timezone.utc)
    if end_timestamp.tzinfo is None:
        end_timestamp = end_timestamp.replace(tzinfo=timezone.utc)

    filter_config = _resolve_filter_config(sym, db)

    def _identify_with_range_retry(slice_candles: list) -> dict[str, Any]:
        r = identify_trend(slice_candles, **filter_config)
        if r.get("trend") == "range":
            r = identify_trend(
                slice_candles,
                trend_confirmation_pct=0.005,
                **{k: v for k, v in filter_config.items() if k != "trend_confirmation_pct"},
            )
        return r

    try_timeframes = ["1d", "4h", "1h", "30m", "15m"]
    src_idx = _tf_ladder_index(source_tf)

    chosen_timeframe: str | None = None
    chosen_candles: list | None = None
    chosen_result: dict[str, Any] | None = None

    for tf in try_timeframes:
        tf_idx = _tf_ladder_index(tf)
        if tf_idx < 0:
            continue
        # Skip same-as or higher (coarser) than reference timeframe.
        if src_idx >= 0 and tf_idx <= src_idx:
            continue
        try:
            tf_all = _fetch_candles_safe(sym, tf, db)
            tf_window = _candles_in_closed_interval(tf_all, start_timestamp, end_timestamp)
            if len(tf_window) < 3:
                continue
            tf_result = _identify_with_range_retry(tf_window)
            # Keep the lowest (finest) valid timeframe fallback with >= 3 candles.
            chosen_timeframe = tf
            chosen_candles = tf_window
            chosen_result = tf_result
            tf_confirmed = _confirmed_leg_count(tf_result.get("legs"))
            if tf_confirmed >= 3:
                break
        except Exception as exc:
            logger.warning(
                "candidate_impulse timeframe attempt failed symbol=%s tf=%s: %s",
                sym,
                tf,
                exc,
            )
            continue

    if chosen_timeframe is None or chosen_candles is None or chosen_result is None:
        return None

    source_tf = chosen_timeframe
    candidate_candles = chosen_candles
    result = chosen_result

    compute_internal_structure(candidate_candles, result["legs"], **filter_config)

    legs_raw = result.get("legs") or []
    stored_legs = [leg for leg in legs_raw if isinstance(leg, dict)]
    if not stored_legs:
        return None
    confirmed_legs = [leg for leg in stored_legs if leg.get("confirmed")]

    prime_leg = _largest_confirmed_impulse_leg(confirmed_legs)
    prime_choch_zone_json: dict[str, Any] | None = None
    if prime_leg is not None:
        p_si = int(prime_leg.get("start_index") or 0)
        p_ei = int(prime_leg.get("end_index") or p_si)
        p_si = max(0, min(p_si, len(candidate_candles) - 1))
        p_ei = max(p_si, min(p_ei, len(candidate_candles) - 1))
        prime_slice = candidate_candles[p_si : p_ei + 1]
        if len(prime_slice) >= 5:
            prime_result = identify_trend(prime_slice, **filter_config)
            if prime_result.get("trend") == "range":
                prime_result = identify_trend(
                    prime_slice,
                    trend_confirmation_pct=0.005,
                    **{k: v for k, v in filter_config.items() if k != "trend_confirmation_pct"},
                )
            compute_internal_structure(prime_slice, prime_result["legs"], **filter_config)
            prime_active = get_active_choch_zone(
                prime_result["legs"],
                prime_result.get("trend", "range"),
                prime_slice,
            )
            if prime_active and isinstance(prime_active.get("choch_zone"), dict):
                prime_choch_zone_json = _json_safe(prime_active["choch_zone"])

    # Candidate walker: run walk_structure on the full candidate candles
    candidate_walker_json: dict[str, Any] | None = None
    try:
        compute_internal_structure(candidate_candles, result["legs"], **filter_config)
        compute_internal_structure_levels(candidate_candles, result["legs"])
        candidate_state_report = walk_structure(
            candidate_candles,
            result,
            filter_config,
            max_depth=2,
            symbol=sym,
            deepening_timeframes=["15m", "5m"],
        )
        candidate_walker_json = _json_safe(serialize_state_report(candidate_state_report))
    except Exception:
        logger.exception("candidate walker failed symbol=%s", sym)

    candidate_active = get_active_choch_zone(
        result["legs"],
        result.get("trend", trend),
        candidate_candles,
    )
    candidate_choch_zone_json: dict[str, Any] | None = None
    if candidate_active and isinstance(candidate_active.get("choch_zone"), dict):
        candidate_choch_zone_json = _json_safe(candidate_active["choch_zone"])

    levels = compute_all_structure_levels(
        candidate_candles,
        result.get("legs") or [],
        str(result.get("trend") or trend),
    )
    bos_levels = levels.get("bos_levels") or []

    ref_impulse = _last_confirmed_impulse_leg(gsc.legs_json)
    structure_broken: bool | None = None
    if ref_impulse is not None and ref_impulse.get("end_price") is not None:
        try:
            ref_bos = float(ref_impulse["end_price"])
            structure_broken = structure_broken_from_close(trend, current_price, ref_bos)
        except (TypeError, ValueError):
            structure_broken = None

    now = datetime.now(timezone.utc)
    start_candle = candidate_candles[0]
    start_ts = start_timestamp
    start_price = float(retr.get("end_price")) if retr and retr.get("end_price") is not None else float(start_candle.low if trend == "up" else start_candle.high)

    row = get_stored_candidate_impulse(sym, db)
    payload = {
        "source_timeframe": source_tf,
        "start_price": start_price,
        "start_timestamp": start_ts,
        "choch_source": choch_source,
        "legs_json": _json_safe(stored_legs),
        "bos_levels_json": _json_safe(bos_levels),
        "choch_zone_json": candidate_choch_zone_json,
        "prime_impulse_json": _json_safe(prime_leg) if prime_leg is not None else None,
        "prime_choch_zone_json": prime_choch_zone_json,
        "structure_broken": structure_broken,
        "candidate_walker_json": candidate_walker_json,
        "computed_at": now,
    }

    if row is None:
        row = CandidateImpulseCache(symbol=sym, **payload)
        db.add(row)
    else:
        for key, val in payload.items():
            setattr(row, key, val)

    db.commit()
    db.refresh(row)
    return row


def upsert_stored_walker_result(
    db: Session,
    sym: str,
    source_timeframe: str,
    serialized: dict[str, Any],
) -> StoredWalkerResult:
    """Insert or update StoredWalkerResult from serialize_state_report output."""
    symbol_upper = sym.strip().upper()
    now = datetime.now(timezone.utc)
    safe_json = _json_safe(serialized)
    row = (
        db.query(StoredWalkerResult)
        .filter(StoredWalkerResult.symbol == symbol_upper)
        .one_or_none()
    )
    payload = {
        "source_timeframe": source_timeframe.strip().lower(),
        "walker_state_json": safe_json,
        "max_depth_reached": int(safe_json.get("max_depth_reached") or 0),
        "total_mitigation_count": int(safe_json.get("total_mitigation_count") or 0),
        "waiting_for": safe_json.get("waiting_for"),
        "global_choch_zone_json": safe_json.get("global_choch_zone"),
        "computed_at": now,
    }
    if row is None:
        row = StoredWalkerResult(symbol=symbol_upper, **payload)
        db.add(row)
    else:
        for key, val in payload.items():
            setattr(row, key, val)
    db.commit()
    db.refresh(row)
    return row


def compute_walker_for_symbol(
    symbol: str,
    db: Session,
) -> StoredWalkerResult | None:
    """
    Pick 4h/1h/30m by confirmed leg count on global-cache retracement window,
    run structural walk on full cached candles, persist StoredWalkerResult.
    Requires GlobalStructureCache and PrimeImpulseStructure rows.
    """
    sym = symbol.strip().upper()
    filter_config = _resolve_filter_config(sym, db)
    gsc = get_stored_global_structure(sym, db)
    if gsc is None:
        return None
    if get_stored_prime_impulse_structure(sym, db) is None:
        return None

    retr = _last_confirmed_retracement_leg(gsc.legs_json)
    if retr is None:
        return None
    t0 = _parse_ts_json(retr.get("start_timestamp"))
    t1 = _parse_ts_json(retr.get("end_timestamp"))
    if t0 is None or t1 is None:
        return None

    candidates: list[tuple[str, int]] = []
    for tf in WALKER_CANDIDATE_TFS:
        all_c = _fetch_candles_safe(sym, tf, db)
        slice_c = _candles_in_closed_interval(all_c, t0, t1)
        if len(slice_c) < 10:
            continue
        sub = identify_trend(slice_c, **filter_config)
        cnt = _confirmed_leg_count(sub.get("legs"))
        candidates.append((tf, cnt))

    if not candidates:
        return None

    win_tf: str | None = None
    for tf, cnt in candidates:
        if cnt >= 3:
            win_tf = tf
            break
    if win_tf is None:
        win_tf, _ = max(candidates, key=lambda x: (x[1], _tf_ladder_index(x[0])))

    all_c = _fetch_candles_safe(sym, win_tf, db)
    if len(all_c) < 10:
        return None

    result_full = identify_trend(all_c, **filter_config)
    compute_internal_structure(
        all_c, result_full["legs"], **filter_config
    )
    compute_internal_structure_levels(all_c, result_full["legs"])
    state_report = walk_structure(
        all_c,
        result_full,
        filter_config,
        max_depth=WALKER_MAX_DEPTH,
        symbol=sym,
        deepening_timeframes=list(WALKER_DEEPENING_TFS),
    )
    serialized = serialize_state_report(state_report)
    row = upsert_stored_walker_result(db, sym, win_tf, serialized)
    try:
        compute_candidate_impulse_for_symbol(sym, db)
    except Exception as exc:
        logger.warning("Candidate impulse failed for %s: %s", sym, exc)
    return row


def compute_walker_all(db: Session) -> dict[str, int]:
    symbols = (
        db.query(MonitoredSetup.symbol).distinct().order_by(MonitoredSetup.symbol.asc()).all()
    )
    success = 0
    failure = 0
    for (sym,) in symbols:
        if not sym:
            continue
        try:
            row = compute_walker_for_symbol(sym, db)
            if row is None:
                failure += 1
                logger.warning("walker skipped (no data) symbol=%s", sym)
            else:
                success += 1
                logger.info("stored_walker ok symbol=%s", sym)
        except Exception:
            failure += 1
            logger.exception("stored_walker failed symbol=%s", sym)
    total = success + failure
    logger.info(
        "stored_walker batch done success=%s failure=%s total=%s",
        success,
        failure,
        total,
    )
    return {"success": success, "failure": failure, "total": total}


def get_stored_walker(symbol: str, db: Session) -> StoredWalkerResult | None:
    sym = symbol.strip().upper()
    return (
        db.query(StoredWalkerResult)
        .filter(StoredWalkerResult.symbol == sym)
        .one_or_none()
    )


MARKET_STATES = [
    "WAITING",
    "RETRACEMENT",
    "DEPTH_BUILDING",
    "CHOCH_ZONE_ACTIVE",
    "CHOCH_TESTED",
    "CANDIDATE_ACTIVE",
    "CANDIDATE_CHOCH_TESTED",
    "ENTRY_ZONE",
    "CANDIDATE_CONFIRMED",
    "STRUCTURE_BROKEN",
]


def compute_market_state(symbol: str, db: Session) -> str:
    sym = symbol.strip().upper()

    gsc = get_stored_global_structure(sym, db)
    if gsc is None or gsc.trend_direction in (None, "range"):
        return "WAITING"

    legs = gsc.legs_json or []
    last_retracement = _last_confirmed_retracement_leg(legs)
    if last_retracement is None:
        return "WAITING"

    sw = get_stored_walker(sym, db)
    walker_depth = int(sw.max_depth_reached or 0) if sw else 0
    walker_state = sw.walker_state_json or {} if sw else {}
    walker_levels = walker_state.get("levels") or []

    if walker_depth == 0:
        return "RETRACEMENT"

    choch_zone = gsc.choch_zone_json
    pis = get_stored_prime_impulse_structure(sym, db)
    prime_choch = pis.choch_zone_json if pis else None

    if not choch_zone and not prime_choch:
        return "DEPTH_BUILDING"

    ci = get_stored_candidate_impulse(sym, db)

    if ci is None:
        return "CHOCH_ZONE_ACTIVE"

    candidate_legs = ci.legs_json or []
    confirmed_candidate = [
        l for l in candidate_legs
        if isinstance(l, dict) and l.get("confirmed")
    ]

    if len(confirmed_candidate) == 0:
        return "CHOCH_TESTED"

    if ci.structure_broken:
        return "STRUCTURE_BROKEN"

    if len(confirmed_candidate) >= 2:
        candidate_walker = ci.candidate_walker_json or {}
        cw_levels = candidate_walker.get("levels") or []
        cw_choch = candidate_walker.get("global_choch_zone")

        if cw_choch:
            cw_zone_tested = any(
                lv.get("crossing_attempt") is not None
                for lv in cw_levels
            )
            if cw_zone_tested:
                return "ENTRY_ZONE"
            return "CANDIDATE_CHOCH_TESTED"

        if ci.prime_choch_zone_json:
            return "CANDIDATE_CHOCH_TESTED"

    return "CANDIDATE_ACTIVE"


def write_market_state(
    symbol: str,
    state: str,
    db: Session,
    score: float | None = None,
    trend_score: float | None = None,
) -> None:
    from src.db.models import MarketStateHistory, MonitoredSetup

    sym = symbol.strip().upper()
    now = datetime.now(timezone.utc)

    gsc = get_stored_global_structure(sym, db)
    previous_state = gsc.market_state if gsc else None

    if gsc is not None:
        gsc.market_state = state
        db.add(gsc)

    ms = db.query(MonitoredSetup).filter(
        MonitoredSetup.symbol == sym
    ).first()
    if ms is not None:
        ms.market_state = state
        db.add(ms)

    if previous_state != state:
        db.add(MarketStateHistory(
            symbol=sym,
            state=state,
            previous_state=previous_state,
            transitioned_at=now,
            score=score,
            trend_score=trend_score,
            notes=None,
        ))

    db.commit()


def compute_and_write_market_state(
    symbol: str,
    db: Session,
    score: float | None = None,
    trend_score: float | None = None,
) -> str:
    state = compute_market_state(symbol, db)
    write_market_state(symbol, state, db, score=score, trend_score=trend_score)
    return state


def cleanup_market_state_history(db: Session, days: int = 90) -> int:
    from src.db.models import MarketStateHistory
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = db.query(MarketStateHistory).filter(
        MarketStateHistory.transitioned_at < cutoff
    ).delete()
    db.commit()
    return deleted
