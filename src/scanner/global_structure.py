"""Compute and persist reference global structure (daily vs weekly) per symbol."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.cache import candle_store
from src.cache.candle_store import CandleDataError
from src.core.choch_zone import get_active_choch_zone
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.structure_levels import compute_all_structure_levels, compute_internal_structure_levels
from src.core.structural_walker import serialize_state_report, walk_structure
from src.core.trend_id import compute_internal_structure, identify_trend
from src.db.models import (
    GlobalStructureCache,
    MonitoredSetup,
    PrimeImpulseStructure,
    StoredWalkerResult,
)

logger = logging.getLogger(__name__)

TIMEFRAME_LADDER = ["1mo", "1w", "1d", "4h", "1h", "30m", "15m", "5m"]

WALKER_CANDIDATE_TFS = ["4h", "1h", "30m"]
WALKER_DEEPENING_TFS = ["4h", "1h", "30m"]
WALKER_MAX_DEPTH = 3


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


def compute_global_structure_for_symbol(symbol: str, db: Session) -> GlobalStructureCache:
    """
    Pick daily vs weekly identify_trend result by confirmed leg count (weekly wins ties),
    compute BOS / CHoCH / active zone, upsert GlobalStructureCache, commit, return row.
    """
    sym = symbol.strip().upper()
    daily_candles = _fetch_candles_safe(sym, "1d", db)
    weekly_candles = _fetch_candles_safe(sym, "1w", db)

    if not daily_candles and not weekly_candles:
        raise ValueError(f"No candle data available for {sym} on 1d or 1w")

    daily_result = identify_trend(daily_candles, **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
    weekly_result = identify_trend(weekly_candles, **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)

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

    legs_raw = winning_result.get("legs") or []
    trend = str(winning_result.get("trend") or "range")

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

    row = db.query(GlobalStructureCache).filter(GlobalStructureCache.symbol == sym).one_or_none()
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


def compute_prime_impulse_structure(symbol: str, db: Session) -> PrimeImpulseStructure:
    """
    Pick the finest of three timeframes below global reference with the richest
    identify_trend on candles inside the last confirmed global impulse window.
    """
    sym = symbol.strip().upper()
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
        sub = identify_trend(slice_c, **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
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


def compute_walker_for_symbol(symbol: str, db: Session) -> StoredWalkerResult | None:
    """
    Pick 4h/1h/30m by confirmed leg count on global-cache retracement window,
    run structural walk on full cached candles, persist StoredWalkerResult.
    Requires GlobalStructureCache and PrimeImpulseStructure rows.
    """
    sym = symbol.strip().upper()
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
        sub = identify_trend(slice_c, **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
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

    result_full = identify_trend(all_c, **SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
    compute_internal_structure(
        all_c, result_full["legs"], **SCAN_AND_ANALYSIS_FILTER_DEFAULTS
    )
    compute_internal_structure_levels(all_c, result_full["legs"])
    state_report = walk_structure(
        all_c,
        result_full,
        SCAN_AND_ANALYSIS_FILTER_DEFAULTS,
        max_depth=WALKER_MAX_DEPTH,
        symbol=sym,
        deepening_timeframes=list(WALKER_DEEPENING_TFS),
    )
    serialized = serialize_state_report(state_report)
    return upsert_stored_walker_result(db, sym, win_tf, serialized)


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
