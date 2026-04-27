from __future__ import annotations

import copy
import hashlib
import json
import json as _json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.adapters.deriv_data import fetch_deriv_ohlc_sync
from src.adapters.yfinance_data import fetch_yfinance_ohlc_sync, is_yfinance_symbol
from src.api.routers.setups import _infer_category
from src.cache import candle_store
from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS
from src.core.choch_zone import compute_choch_zone, get_active_choch_zone
from src.core.structure_levels import (
    compute_all_structure_levels,
    compute_internal_structure_levels,
    compute_last_impulse_internal_choch_zone,
)
from src.core.structural_walker import (
    RMT_DEFAULT_FILTER_CONFIG,
    serialize_state_report,
    walk_structure,
)
from src.scanner.global_structure import get_stored_walker
from src.core.choch_candidate_move import (
    find_candidate_pivot_index,
    reference_bos_before_pivot,
    structure_broken_from_close,
)
from src.core.trend_id import compute_internal_structure, identify_trend
from src.db.models import (
    AnalysisResultCache,
    CandidateImpulseCache,
    GlobalStructureCache,
    ManualStructureOverride,
    MonitoredSetup,
    PaperTrade,
)
from src.db.session import get_db
from src.scanner.global_structure import get_stored_global_structure, get_stored_prime_impulse_structure
from src.services.structure_deepening import apply_tf_deepening_to_legs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
universe_router = APIRouter(prefix="/api/universe", tags=["analysis"])

_TF_WINDOWS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "timeframe_windows.yaml"
with _TF_WINDOWS_PATH.open(encoding="utf-8") as _tf_f:
    _TF_WINDOWS: dict[str, Any] = yaml.safe_load(_tf_f)

# Chart overlay colors (global across markets; keep in sync with frontend structure-colors.ts)
STRUCTURE_GLOBAL_CHOCH_COLOR = "#E91E63"
STRUCTURE_INTERNAL_CHOCH_COLOR = "#FF9800"
STRUCTURE_CANDIDATE_MOVE_COLOR = "#4DD0E1"

FILTER_CONFIG: dict[str, Any] = dict(SCAN_AND_ANALYSIS_FILTER_DEFAULTS)
# Market View debug (GET /api/analysis/{symbol} query overrides) â€” baseline inventory:
# - FILTER_CONFIG keys â†’ identify_trend, compute_internal_structure, walk_structure (filter_config),
#   _enrich_internal_structure_with_tf_deepening (same six keys; fine-TF deepening keeps tcp=0.005).
# - Optional queries min_swing_candles, trend_confirmation_pct â†’ main chart identify/compute only
#   (defaults: min_swing_candles=3, outer trend_confirmation_pct=0.03; internal slices in core use 0.005).
# - max_walk_depth â†’ walk_structure(..., max_depth=...) (router default 3).
# - rmt_* queries â†’ walk_structure(..., rmt_filter_config=...) else RMT_DEFAULT_FILTER_CONFIG in walker.
# - symbol â†’ walk_structure(..., symbol=...) for adapter-routed TF deepening; optional deepening_timeframes.

_DEFAULT_WALK_DEPTH = 3
_DEFAULT_MIN_SWING_CANDLES = 3
_DEFAULT_TREND_CONFIRMATION_PCT = 0.03


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _layer_cache_timestamps(
    symbol: str,
    db: Session,
    *,
    gsc: GlobalStructureCache | None = None,
    pis: Any | None = None,
    walker: Any | None = None,
    candidate: CandidateImpulseCache | None = None,
) -> dict[str, str | None]:
    global_row = gsc if gsc is not None else get_stored_global_structure(symbol, db)
    prime_row = pis if pis is not None else get_stored_prime_impulse_structure(symbol, db)
    walker_row = walker if walker is not None else get_stored_walker(symbol, db)
    candidate_row = candidate if candidate is not None else get_stored_candidate_impulse(symbol, db)
    return {
        "global": _iso_or_none(getattr(global_row, "computed_at", None)),
        "prime": _iso_or_none(getattr(prime_row, "computed_at", None)),
        "walker": _iso_or_none(getattr(walker_row, "computed_at", None)),
        "candidate": _iso_or_none(getattr(candidate_row, "computed_at", None)),
    }


def _analysis_cache_params_for_hash(
    *,
    min_swing_candles: int | None,
    trend_confirmation_pct: float | None,
    use_parent_relative_filter: bool | None,
    min_impulse_parent_ratio: float | None,
    use_momentum_filter: bool | None,
    min_momentum_ratio: float | None,
    use_dominance_filter: bool | None,
    min_dominance_ratio: float | None,
    max_walk_depth: int | None,
    rmt_use_parent_relative_filter: bool | None,
    rmt_min_impulse_parent_ratio: float | None,
    rmt_use_momentum_filter: bool | None,
    rmt_min_momentum_ratio: float | None,
    rmt_use_dominance_filter: bool | None,
    rmt_min_dominance_ratio: float | None,
) -> dict[str, Any]:
    """Stable dict for cache key: effective tuning only (no symbol/timeframe/request metadata)."""
    trend_kw = dict(
        _merge_trend_filter_kwargs(
            min_swing_candles=min_swing_candles,
            trend_confirmation_pct=trend_confirmation_pct,
            use_parent_relative_filter=use_parent_relative_filter,
            min_impulse_parent_ratio=min_impulse_parent_ratio,
            use_momentum_filter=use_momentum_filter,
            min_momentum_ratio=min_momentum_ratio,
            use_dominance_filter=use_dominance_filter,
            min_dominance_ratio=min_dominance_ratio,
        )
    )
    trend_kw.setdefault("min_swing_candles", _DEFAULT_MIN_SWING_CANDLES)
    trend_kw.setdefault("trend_confirmation_pct", _DEFAULT_TREND_CONFIRMATION_PCT)
    rmt_kw = _merge_rmt_filter_kwargs(
        rmt_use_parent_relative_filter=rmt_use_parent_relative_filter,
        rmt_min_impulse_parent_ratio=rmt_min_impulse_parent_ratio,
        rmt_use_momentum_filter=rmt_use_momentum_filter,
        rmt_min_momentum_ratio=rmt_min_momentum_ratio,
        rmt_use_dominance_filter=rmt_use_dominance_filter,
        rmt_min_dominance_ratio=rmt_min_dominance_ratio,
    )
    rmt_eff = dict(rmt_kw) if rmt_kw is not None else dict(RMT_DEFAULT_FILTER_CONFIG)
    walk_depth = _DEFAULT_WALK_DEPTH if max_walk_depth is None else max_walk_depth
    return {
        "trend": {k: trend_kw[k] for k in sorted(trend_kw.keys())},
        "rmt": {k: rmt_eff[k] for k in sorted(rmt_eff.keys())},
        "max_walk_depth": walk_depth,
    }


def _try_stored_walker_json(
    db: Session,
    symbol_upper: str,
    candle_tf_lower: str,
    rmt_kw: dict[str, Any] | None,
    walk_depth: int,
) -> dict[str, Any] | None:
    """Return deep-copied serialized walker state when default walker params are used."""
    if rmt_kw is not None or walk_depth != _DEFAULT_WALK_DEPTH:
        return None
    sw = get_stored_walker(symbol_upper, db)
    if sw is None:
        return None
    raw = sw.walker_state_json
    if not isinstance(raw, dict) or not raw:
        return None
    return copy.deepcopy(raw)


def _http_from_candle_error(exc: candle_store.CandleDataError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "reason": exc.reason,
            "message": str(exc),
        },
    )


def _get_candles_from_store(db: Session, symbol_upper: str, tf: str) -> list:
    try:
        return candle_store.get_candles(symbol_upper, tf.lower(), db)
    except candle_store.CandleDataError as exc:
        raise _http_from_candle_error(exc) from exc


def _trend_kw_without_tcp(cfg: dict[str, Any]) -> dict[str, Any]:
    """Drop trend_confirmation_pct so callers can pass a fixed tcp (e.g. 0.005 for fine-TF deepening)."""
    return {k: v for k, v in cfg.items() if k != "trend_confirmation_pct"}


def _merge_trend_filter_kwargs(
    *,
    min_swing_candles: int | None,
    trend_confirmation_pct: float | None,
    use_parent_relative_filter: bool | None,
    min_impulse_parent_ratio: float | None,
    use_momentum_filter: bool | None,
    min_momentum_ratio: float | None,
    use_dominance_filter: bool | None,
    min_dominance_ratio: float | None,
) -> dict[str, Any]:
    cfg = dict(FILTER_CONFIG)
    if min_swing_candles is not None:
        cfg["min_swing_candles"] = min_swing_candles
    if trend_confirmation_pct is not None:
        cfg["trend_confirmation_pct"] = trend_confirmation_pct
    if use_parent_relative_filter is not None:
        cfg["use_parent_relative_filter"] = use_parent_relative_filter
    if min_impulse_parent_ratio is not None:
        cfg["min_impulse_parent_ratio"] = min_impulse_parent_ratio
    if use_momentum_filter is not None:
        cfg["use_momentum_filter"] = use_momentum_filter
    if min_momentum_ratio is not None:
        cfg["min_momentum_ratio"] = min_momentum_ratio
    if use_dominance_filter is not None:
        cfg["use_dominance_filter"] = use_dominance_filter
    if min_dominance_ratio is not None:
        cfg["min_dominance_ratio"] = min_dominance_ratio
    return cfg


def _merge_rmt_filter_kwargs(
    *,
    rmt_use_parent_relative_filter: bool | None,
    rmt_min_impulse_parent_ratio: float | None,
    rmt_use_momentum_filter: bool | None,
    rmt_min_momentum_ratio: float | None,
    rmt_use_dominance_filter: bool | None,
    rmt_min_dominance_ratio: float | None,
) -> dict[str, Any] | None:
    if all(
        v is None
        for v in (
            rmt_use_parent_relative_filter,
            rmt_min_impulse_parent_ratio,
            rmt_use_momentum_filter,
            rmt_min_momentum_ratio,
            rmt_use_dominance_filter,
            rmt_min_dominance_ratio,
        )
    ):
        return None
    cfg = dict(RMT_DEFAULT_FILTER_CONFIG)
    if rmt_use_parent_relative_filter is not None:
        cfg["use_parent_relative_filter"] = rmt_use_parent_relative_filter
    if rmt_min_impulse_parent_ratio is not None:
        cfg["min_impulse_parent_ratio"] = rmt_min_impulse_parent_ratio
    if rmt_use_momentum_filter is not None:
        cfg["use_momentum_filter"] = rmt_use_momentum_filter
    if rmt_min_momentum_ratio is not None:
        cfg["min_momentum_ratio"] = rmt_min_momentum_ratio
    if rmt_use_dominance_filter is not None:
        cfg["use_dominance_filter"] = rmt_use_dominance_filter
    if rmt_min_dominance_ratio is not None:
        cfg["min_dominance_ratio"] = rmt_min_dominance_ratio
    return cfg


def _validate_trend_query_params(
    *,
    min_swing_candles: int | None,
    trend_confirmation_pct: float | None,
    min_impulse_parent_ratio: float | None,
    min_momentum_ratio: float | None,
    min_dominance_ratio: float | None,
    max_walk_depth: int | None,
    rmt_min_impulse_parent_ratio: float | None,
    rmt_min_momentum_ratio: float | None,
    rmt_min_dominance_ratio: float | None,
) -> None:
    if min_swing_candles is not None and not (1 <= min_swing_candles <= 20):
        raise HTTPException(status_code=422, detail="min_swing_candles must be between 1 and 20")
    if trend_confirmation_pct is not None and not (0.0001 <= trend_confirmation_pct <= 0.5):
        raise HTTPException(
            status_code=422,
            detail="trend_confirmation_pct must be between 0.0001 and 0.5",
        )
    for name, val in (
        ("min_impulse_parent_ratio", min_impulse_parent_ratio),
        ("min_momentum_ratio", min_momentum_ratio),
        ("min_dominance_ratio", min_dominance_ratio),
        ("rmt_min_impulse_parent_ratio", rmt_min_impulse_parent_ratio),
        ("rmt_min_momentum_ratio", rmt_min_momentum_ratio),
        ("rmt_min_dominance_ratio", rmt_min_dominance_ratio),
    ):
        if val is not None and not (0.001 <= val <= 5.0):
            raise HTTPException(status_code=422, detail=f"{name} must be between 0.001 and 5.0")
    if max_walk_depth is not None and not (1 <= max_walk_depth <= 10):
        raise HTTPException(status_code=422, detail="max_walk_depth must be between 1 and 10")

def _enrich_internal_structure_with_tf_deepening(
    candles: list,
    legs: list,
    filter_config: dict[str, Any],
    symbol: str,
) -> None:
    """Delegate to shared iterative 15m/5m deepening."""
    apply_tf_deepening_to_legs(candles, legs, filter_config, symbol)


def _parse_ts(value: Any) -> datetime | None:
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


def _candles_in_closed_interval_chart(
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


def _nearest_candle_index(candles: list, target_dt: datetime) -> int:
    if not candles:
        return 0
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    target_sec = int(target_dt.timestamp())
    best_i = 0
    best_diff = float("inf")
    for i, c in enumerate(candles):
        ct = c.timestamp
        if not isinstance(ct, datetime):
            continue
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        sec = int(ct.timestamp())
        diff = abs(sec - target_sec)
        if diff < best_diff:
            best_diff = diff
            best_i = i
    return best_i


def _ref_tf_from_cache_row(gsc: GlobalStructureCache) -> str:
    rt = (gsc.reference_timeframe or "").lower()
    if rt == "weekly":
        return "1w"
    return "1d"


def _remap_ref_index_to_chart(
    ref_candles: list,
    chart_candles: list,
    ref_idx: int | None,
) -> int | None:
    if ref_idx is None or not ref_candles or not chart_candles:
        return None
    ri = int(ref_idx)
    if ri < 0 or ri >= len(ref_candles):
        return None
    ts = ref_candles[ri].timestamp
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return _nearest_candle_index(chart_candles, ts)


def _remap_bos_dict_to_chart(
    b: dict[str, Any],
    ref_candles: list,
    chart_candles: list,
) -> dict[str, Any] | None:
    chart_si = _remap_ref_index_to_chart(ref_candles, chart_candles, int(b["start_index"]))
    if chart_si is None:
        return None
    out = dict(b)
    out["start_index"] = chart_si
    if b.get("broken") and b.get("break_index") is not None:
        cbi = _remap_ref_index_to_chart(ref_candles, chart_candles, int(b["break_index"]))
        out["break_index"] = cbi if cbi is not None else chart_si
    return out


def _remap_cached_legs_to_chart(legs_json: list[Any], chart_candles: list) -> list[dict[str, Any]]:
    n = len(chart_candles)
    if n == 0:
        return []
    out: list[dict[str, Any]] = []
    for leg in legs_json or []:
        if not isinstance(leg, dict):
            continue
        lg = copy.deepcopy(leg)
        st = _parse_ts(lg.get("start_timestamp"))
        et = _parse_ts(lg.get("end_timestamp"))
        if st is not None:
            si = _nearest_candle_index(chart_candles, st)
        elif lg.get("start_index") is not None:
            si = max(0, min(int(lg["start_index"]), n - 1))
        else:
            si = 0
        if et is not None:
            ei = _nearest_candle_index(chart_candles, et)
        else:
            ei = n - 1
        si = max(0, min(si, n - 1))
        ei = max(0, min(ei, n - 1))
        if si > ei:
            si = ei
        lg["start_index"] = si
        lg["end_index"] = ei
        out.append(lg)
    return out


def _leg_span_key(leg: dict[str, Any]) -> tuple[int | None, int | None]:
    si = leg.get("start_index")
    ei = leg.get("end_index")
    return (
        int(si) if si is not None else None,
        int(ei) if ei is not None else None,
    )


def _serialize_prime_internal_legs_for_chart(
    chart_candles: list,
    prime_legs_json: list[Any],
    prime_slice_candles: list,
) -> list[dict[str, Any]]:
    n = len(chart_candles)
    if n == 0 or not prime_slice_candles:
        return []
    out: list[dict[str, Any]] = []
    for il in prime_legs_json or []:
        if not isinstance(il, dict) or not il.get("confirmed"):
            continue
        st = _parse_ts(il.get("start_timestamp"))
        et = _parse_ts(il.get("end_timestamp"))
        if st is not None:
            chart_si = _nearest_candle_index(chart_candles, st)
        else:
            rmsi = il.get("start_index")
            if rmsi is None:
                continue
            remapped = _remap_ref_index_to_chart(
                prime_slice_candles, chart_candles, int(rmsi)
            )
            if remapped is None:
                continue
            chart_si = remapped
        if et is not None:
            chart_ei = _nearest_candle_index(chart_candles, et)
        else:
            rmei = il.get("end_index")
            if rmei is not None:
                remapped_e = _remap_ref_index_to_chart(
                    prime_slice_candles, chart_candles, int(rmei)
                )
                chart_ei = remapped_e if remapped_e is not None else chart_si
            else:
                chart_ei = n - 1
        chart_si = max(0, min(int(chart_si), n - 1))
        chart_ei = max(0, min(int(chart_ei), n - 1))
        if chart_si > chart_ei:
            chart_si = chart_ei
        try:
            sp = float(il["start_price"])
        except (KeyError, TypeError, ValueError):
            continue
        ep: float | None = None
        if il.get("end_price") is not None:
            try:
                ep = float(il["end_price"])
            except (TypeError, ValueError):
                ep = None
        out.append(
            {
                "type": str(il.get("type", "unknown")),
                "start_price": sp,
                "end_price": ep,
                "start_index": chart_si,
                "end_index": chart_ei,
                "start_timestamp": chart_candles[chart_si].timestamp.isoformat(),
                "end_timestamp": chart_candles[chart_ei].timestamp.isoformat(),
                "confirmed": True,
            }
        )
    return out


def _prime_internal_choch_zone_for_chart(
    chart_candles: list,
    choch_zone_json: dict[str, Any] | None,
    prime_slice_candles: list,
    trend_hint: str,
    structure_color_override: str | None = None,
) -> dict[str, Any] | None:
    n = len(chart_candles)
    if n == 0 or not prime_slice_candles or not isinstance(choch_zone_json, dict):
        return None
    gsi = _remap_ref_index_to_chart(
        prime_slice_candles,
        chart_candles,
        int(choch_zone_json.get("source_impulse_start_index", 0)),
    )
    if gsi is None or gsi < 0 or gsi >= n:
        return None
    td = choch_zone_json.get("trend_direction") or trend_hint or "up"
    color = structure_color_override or STRUCTURE_INTERNAL_CHOCH_COLOR
    return {
        "lower_boundary": float(choch_zone_json["lower_boundary"]),
        "upper_boundary": float(choch_zone_json["upper_boundary"]),
        "start_timestamp": chart_candles[gsi].timestamp.isoformat(),
        "end_timestamp": chart_candles[-1].timestamp.isoformat(),
        "broken": bool(choch_zone_json.get("broken", False)),
        "trend_direction": str(td),
        "color": color,
    }


def _derive_current_phase_from_legs(legs: list[dict[str, Any]]) -> str:
    confirmed = [lg for lg in legs if lg.get("confirmed")]
    if confirmed:
        return str(confirmed[-1].get("type", "unknown"))
    if legs:
        return str(legs[-1].get("type", "unknown"))
    return "unknown"


def _prime_serializer_kwargs(symbol_upper: str, db: Session) -> dict[str, Any]:
    """Build optional prime-impulse kwargs for ``_serialize_trend_legs_structure``."""
    pis = get_stored_prime_impulse_structure(symbol_upper, db)
    if pis is None:
        return {}
    try:
        full = _get_candles_from_store(db, symbol_upper, pis.source_timeframe)
    except HTTPException:
        return {}
    if not full:
        return {}
    sl = _candles_in_closed_interval_chart(
        full, pis.impulse_start_timestamp, pis.impulse_end_timestamp
    )
    if not sl:
        return {}
    return {
        "prime_slice_candles": sl,
        "prime_legs_json": list(pis.legs_json or []),
        "prime_choch_zone_json": pis.choch_zone_json
        if isinstance(pis.choch_zone_json, dict)
        else None,
        "prime_source_tf": pis.source_timeframe,
    }


def _try_global_cache_result(
    symbol_upper: str,
    db: Session,
    chart_candles: list,
) -> tuple[dict[str, Any], list, GlobalStructureCache] | None:
    gsc = get_stored_global_structure(symbol_upper, db)
    if gsc is None:
        return None
    try:
        ref_candles = _get_candles_from_store(db, symbol_upper, _ref_tf_from_cache_row(gsc))
    except HTTPException:
        return None
    if not ref_candles or not chart_candles:
        return None
    legs = _remap_cached_legs_to_chart(gsc.legs_json or [], chart_candles)
    if not legs:
        return None
    trend = (gsc.trend_direction or "range").lower()
    result: dict[str, Any] = {
        "trend": trend,
        "legs": legs,
        "current_phase": _derive_current_phase_from_legs(legs),
    }
    return (result, ref_candles, gsc)


def _parse_state(raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _compute_new_move_analysis(
    candles: list,
    state_report: dict[str, Any],
    symbol: str,
    filter_config: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Analyze the move from the CHoCH extreme to current price.
    This is the candidate next impulse â€” the entry signal source.
    Uses crossing_attempt from depth 1 of the structural walk.
    """
    levels = state_report.get("levels", [])
    if not levels:
        return None

    depth1 = levels[0]
    crossing = depth1.get("crossing_attempt")
    if not crossing:
        return None

    move_start_idx = crossing.get("global_start_index")
    if move_start_idx is None:
        return None

    move_candles = candles[int(move_start_idx) :]
    if len(move_candles) < 5:
        return None

    try:
        move_result = identify_trend(move_candles, **filter_config)
        if move_result.get("trend") == "range":
            move_result = identify_trend(
                move_candles,
                trend_confirmation_pct=0.005,
                **_trend_kw_without_tcp(filter_config),
            )
        compute_internal_structure(move_candles, move_result["legs"], **filter_config)
        _enrich_internal_structure_with_tf_deepening(
            move_candles, move_result["legs"], filter_config, symbol
        )
        compute_internal_structure_levels(move_candles, move_result["legs"])

        move_choch = get_active_choch_zone(
            move_result["legs"],
            move_result["trend"],
            move_candles,
        )

        current_price = float(move_candles[-1].close)
        choch_reached = False
        choch_zone = None
        if move_choch and move_choch.get("choch_zone"):
            zone = move_choch["choch_zone"]
            choch_zone = zone
            lower = float(zone["lower_boundary"])
            upper = float(zone["upper_boundary"])
            choch_reached = lower <= current_price <= upper or current_price < lower

        move_leg_payload = _serialize_trend_legs_structure(move_candles, move_result)

        entry_price = current_price
        stop_loss = float(crossing.get("start_price", 0))
        target = None
        if levels and levels[0].get("structural_level"):
            target = float(levels[0]["structural_level"]["price"])

        zone_payload = None
        if choch_zone:
            src_idx = int(choch_zone.get("source_impulse_start_index", 0) or 0)
            if src_idx < 0:
                src_idx = 0
            if src_idx >= len(move_candles):
                src_idx = len(move_candles) - 1
            zone_payload = {
                "depth": 1,
                "lower_boundary": float(choch_zone["lower_boundary"]),
                "upper_boundary": float(choch_zone["upper_boundary"]),
                "start_timestamp": move_candles[src_idx].timestamp.isoformat(),
                "end_timestamp": move_candles[-1].timestamp.isoformat(),
                "color": "#9B59B6",
            }

        return {
            "trend": move_result.get("trend"),
            "current_phase": move_result.get("current_phase"),
            "leg_count": sum(1 for l in move_result["legs"] if l.get("confirmed")),
            "legs": move_leg_payload.get("legs", []),
            "bos_levels": move_leg_payload.get("bos_levels", []),
            "choch_zone": zone_payload,
            "choch_reached": choch_reached,
            "move_start_timestamp": move_candles[0].timestamp.isoformat(),
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
        }
    except Exception as e:
        logger.warning("New move analysis failed for %s: %s", symbol, e)
        return None


def _serialize_trend_legs_structure(
    candles: list,
    result: dict[str, Any],
    state_report: dict[str, Any] | None = None,
    structure_color_override: str | None = None,
    *,
    cached_globals: bool = False,
    bos_raw_cached: list[Any] | None = None,
    choch_level_cached: dict[str, Any] | None = None,
    global_choch_zone_cached: dict[str, Any] | None = None,
    ref_candles: list | None = None,
    prime_slice_candles: list | None = None,
    prime_legs_json: list[Any] | None = None,
    prime_choch_zone_json: dict[str, Any] | None = None,
    prime_source_tf: str | None = None,
) -> dict[str, Any]:
    """Build legs, bos_levels, choch_level, choch_zones from an ``identify_trend`` result dict.

    Does not call ``identify_trend`` or ``compute_internal_structure``. Callers must run::

        result = identify_trend(candles, **filter_config)
        compute_internal_structure(candles, result["legs"], **filter_config)
        payload = _serialize_trend_legs_structure(candles, result, state_report)

    Optional ``state_report`` is serialized walker output (``structural_state_json`` shape)
    with ``levels`` â€” used for ``choch_zones`` overlays.

    ``structure_color_override`` (e.g. teal for CHoCH candidate move) sets CHoCH band and BOS line colors.

    When ``cached_globals`` is True, global BOS / CHoCH line / global CHoCH band come from the
    cache (remapped from reference timeframe indices onto ``candles``); ``ref_candles`` must be set.

    When ``prime_source_tf`` and non-empty ``prime_slice_candles`` and ``prime_legs_json`` are set,
    the last confirmed impulse leg uses stored prime internal legs; ``internal_choch_zone`` is built
    from ``prime_choch_zone_json`` when it is a dict (else null).
    """
    trend = result.get("trend", "range")
    prime_active = (
        prime_source_tf is not None
        and prime_slice_candles is not None
        and len(prime_slice_candles) > 0
        and prime_legs_json is not None
    )
    last_impulse_key: tuple[int | None, int | None] | None = None
    if prime_active:
        raw_legs = result.get("legs") or []
        imp_list = [
            lg
            for lg in raw_legs
            if lg.get("confirmed") and lg.get("type") == "impulse"
        ]
        if imp_list:
            last_impulse_key = _leg_span_key(imp_list[-1])
    if cached_globals:
        if not ref_candles:
            raise ValueError("cached_globals requires ref_candles")
        bos_raw = []
        for b in bos_raw_cached or []:
            if not isinstance(b, dict):
                continue
            mb = _remap_bos_dict_to_chart(b, ref_candles, candles)
            if mb is not None:
                bos_raw.append(mb)
        choch = None
        if choch_level_cached and isinstance(choch_level_cached, dict):
            cci = _remap_ref_index_to_chart(
                ref_candles,
                candles,
                int(choch_level_cached["start_index"]),
            )
            if cci is not None:
                choch = {**choch_level_cached, "start_index": cci}
    else:
        levels = compute_all_structure_levels(candles, result.get("legs") or [], trend)
        bos_raw = levels.get("bos_levels") or []
        choch = levels.get("choch_level")

    n = len(candles)

    def _iso_ts_series(series: list, idx: Any) -> str | None:
        if idx is None or not series:
            return None
        i = int(idx)
        if 0 <= i < len(series):
            return series[i].timestamp.isoformat()
        return series[-1].timestamp.isoformat()

    def _outer_iso_ts(idx: int | None) -> str | None:
        if idx is None or not n:
            return None
        if idx < 0 or idx >= n:
            return None
        return candles[idx].timestamp.isoformat()

    legs_out = []
    for leg in result.get("legs") or []:
        if not leg.get("confirmed"):
            continue
        si = int(leg["start_index"]) if leg.get("start_index") is not None else None
        start_timestamp = _outer_iso_ts(si) if si is not None else None
        if leg.get("end_index") is not None and int(leg["end_index"]) < n:
            end_timestamp = candles[int(leg["end_index"])].timestamp.isoformat()
        else:
            end_timestamp = candles[-1].timestamp.isoformat() if n else None

        parent_start = int(leg["start_index"]) if leg.get("start_index") is not None else 0
        parent_end = int(leg["end_index"]) if leg.get("end_index") is not None else (n - 1 if n else 0)

        internal_legs: list[dict[str, Any]] = []
        use_prime_internals = (
            prime_active
            and last_impulse_key is not None
            and leg.get("type") == "impulse"
            and _leg_span_key(leg) == last_impulse_key
        )
        if use_prime_internals:
            internal_legs = _serialize_prime_internal_legs_for_chart(
                candles, prime_legs_json, prime_slice_candles
            )
        elif leg.get("type") == "impulse" and leg.get("confirmed"):
            internal_candles = leg.get("internal_tf_candles")
            for il in (leg.get("internal_structure") or {}).get("legs", []):
                if not il.get("confirmed"):
                    continue
                if internal_candles is not None:
                    ic = internal_candles
                    il_start_timestamp = _iso_ts_series(ic, il.get("start_index"))
                    il_ei = il.get("end_index")
                    end_idx_for_ts = (
                        min(int(il_ei), len(ic) - 1) if il_ei is not None else len(ic) - 1
                    )
                    il_end_timestamp = _iso_ts_series(ic, end_idx_for_ts)
                else:
                    il_si = il.get("start_index")
                    il_start_timestamp = (
                        _iso_ts_series(candles, parent_start + int(il_si))
                        if il_si is not None
                        else None
                    )
                    il_ei = il.get("end_index")
                    if il_ei is not None and n > 0:
                        g_end = min(parent_start + int(il_ei), parent_end, n - 1)
                        il_end_timestamp = _iso_ts_series(candles, g_end)
                    else:
                        il_end_timestamp = None
                internal_legs.append(
                    {
                        "type": il["type"],
                        "start_price": float(il["start_price"]),
                        "end_price": float(il["end_price"]) if il.get("end_price") is not None else None,
                        "start_index": int(il["start_index"]),
                        "end_index": int(il["end_index"]) if il.get("end_index") is not None else None,
                        "start_timestamp": il_start_timestamp,
                        "end_timestamp": il_end_timestamp,
                        "confirmed": bool(il.get("confirmed", False)),
                    }
                )

        legs_out.append(
            {
                "type": leg["type"],
                "start_price": float(leg["start_price"]),
                "end_price": float(leg["end_price"]) if leg.get("end_price") is not None else None,
                "start_index": int(leg["start_index"]),
                "end_index": int(leg["end_index"]) if leg.get("end_index") is not None else None,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "confirmed": bool(leg.get("confirmed", False)),
                "internal_tf_used": prime_source_tf
                if use_prime_internals
                else leg.get("internal_tf_used", "current"),
                "internal_legs": internal_legs,
            }
        )

    def _bos_segment_end_index(b: dict[str, Any]) -> int:
        """Last bar index for the BOS segment: break bar if broken, else last candle."""
        if not n:
            return -1
        bi = b.get("break_index")
        if b.get("broken") and bi is not None:
            ix = int(bi)
            if 0 <= ix < n:
                return ix
        return n - 1

    bos_levels = []
    for b in bos_raw:
        si = int(b["start_index"])
        end_ix = _bos_segment_end_index(b)
        if end_ix < 0:
            end_ix = n - 1 if n else 0
        start_ts = candles[si].timestamp.isoformat() if 0 <= si < n else ""
        end_ts = candles[end_ix].timestamp.isoformat() if 0 <= end_ix < n else ""
        bos_entry: dict[str, Any] = {
            "price": float(b["price"]),
            "start_index": si,
            "start_timestamp": start_ts,
            "end_index": end_ix,
            "end_timestamp": end_ts,
            "broken": bool(b["broken"]),
            "trend_direction": b["trend_direction"],
        }
        if structure_color_override:
            bos_entry["color"] = structure_color_override
        bos_levels.append(bos_entry)

    choch_level: dict[str, Any] | None = None
    if choch:
        ci = int(choch["start_index"])
        start_ts = (
            candles[ci].timestamp.isoformat()
            if n and 0 <= ci < n
            else candles[-1].timestamp.isoformat()
            if n
            else ""
        )
        choch_level = {
            "price": float(choch["price"]),
            "start_index": ci,
            "start_timestamp": start_ts,
            "broken": bool(choch["broken"]),
            "trend_direction": choch["trend_direction"],
        }

    choch_zones: list[dict[str, Any]] = []
    depth_colors = {1: "#2962FF", 2: "#26A69A", 3: "#9C27B0", 4: "#FF9800"}
    if n > 0 and state_report and state_report.get("levels"):
        for level in state_report["levels"]:
            zone = level.get("choch_zone")
            if not zone:
                continue
            g_start = level.get("first_impulse_global_start")
            depth = int(level.get("depth", 1) or 1)
            if g_start is not None and 0 <= int(g_start) < n:
                start_ts = candles[int(g_start)].timestamp.isoformat()
            else:
                start_ts = candles[0].timestamp.isoformat()
            end_ts = candles[-1].timestamp.isoformat()
            choch_zones.append(
                {
                    "depth": depth,
                    "lower_boundary": float(zone["lower_boundary"]),
                    "upper_boundary": float(zone["upper_boundary"]),
                    "start_timestamp": start_ts,
                    "end_timestamp": end_ts,
                    "color": depth_colors.get(depth, "#607D8B"),
                }
            )

    global_choch_zone: dict[str, Any] | None = None
    if trend in ("up", "down") and n > 0:
        if cached_globals and global_choch_zone_cached and isinstance(
            global_choch_zone_cached, dict
        ):
            gsi = _remap_ref_index_to_chart(
                ref_candles,
                candles,
                int(global_choch_zone_cached.get("source_impulse_start_index", 0)),
            )
            if gsi is not None and 0 <= gsi < n:
                global_choch_zone = {
                    "lower_boundary": float(global_choch_zone_cached["lower_boundary"]),
                    "upper_boundary": float(global_choch_zone_cached["upper_boundary"]),
                    "start_timestamp": candles[gsi].timestamp.isoformat(),
                    "end_timestamp": candles[-1].timestamp.isoformat(),
                    "broken": bool(choch["broken"])
                    if choch
                    else bool(global_choch_zone_cached.get("broken", False)),
                    "trend_direction": trend,
                    "color": structure_color_override or STRUCTURE_GLOBAL_CHOCH_COLOR,
                }
        elif not cached_globals:
            gzone = compute_choch_zone(result.get("legs") or [], trend)
            if gzone is not None:
                gsi = int(gzone["source_impulse_start_index"])
                if 0 <= gsi < n:
                    global_choch_zone = {
                        "lower_boundary": float(gzone["lower_boundary"]),
                        "upper_boundary": float(gzone["upper_boundary"]),
                        "start_timestamp": candles[gsi].timestamp.isoformat(),
                        "end_timestamp": candles[-1].timestamp.isoformat(),
                        "broken": bool(choch["broken"]) if choch else False,
                        "trend_direction": trend,
                        "color": structure_color_override or STRUCTURE_GLOBAL_CHOCH_COLOR,
                    }

    internal_choch_zone: dict[str, Any] | None = None
    if prime_active:
        internal_choch_zone = _prime_internal_choch_zone_for_chart(
            candles,
            prime_choch_zone_json,
            prime_slice_candles,
            str(trend),
            structure_color_override,
        )
    else:
        izone = compute_last_impulse_internal_choch_zone(candles, result.get("legs") or [])
        if izone is not None and n > 0:
            igsi = int(izone["source_impulse_start_index_global"])
            if 0 <= igsi < n:
                internal_choch_zone = {
                    "lower_boundary": float(izone["lower_boundary"]),
                    "upper_boundary": float(izone["upper_boundary"]),
                    "start_timestamp": candles[igsi].timestamp.isoformat(),
                    "end_timestamp": candles[-1].timestamp.isoformat(),
                    "broken": bool(izone["broken"]),
                    "trend_direction": izone["trend_direction"],
                    "color": structure_color_override or STRUCTURE_INTERNAL_CHOCH_COLOR,
                }

    return {
        "legs": legs_out,
        "bos_levels": bos_levels,
        "choch_level": choch_level,
        "choch_zones": choch_zones,
        "global_choch_zone": global_choch_zone,
        "internal_choch_zone": internal_choch_zone,
    }


def _last_confirmed_retracement_leg(legs_raw: list[Any]) -> dict[str, Any] | None:
    """Confirmed retracement with greatest end_index (last retracement in normal sequencing)."""
    best: dict[str, Any] | None = None
    best_ei = -1
    for leg in legs_raw:
        if not isinstance(leg, dict):
            continue
        if not leg.get("confirmed") or leg.get("type") != "retracement":
            continue
        ei = leg.get("end_index")
        ep = leg.get("end_price")
        if ei is None or ep is None:
            continue
        try:
            ei_int = int(ei)
        except (TypeError, ValueError):
            continue
        if ei_int > best_ei:
            best_ei = ei_int
            best = leg
    return best


def _candidate_ichoch_reached(
    trend: str,
    teal_structure: dict[str, Any] | None,
    current_price: float,
) -> bool | None:
    if not teal_structure or not isinstance(teal_structure, dict):
        return None
    zone = teal_structure.get("internal_choch_zone")
    if not isinstance(zone, dict):
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
    if trend == "up":
        return current_price <= hi_f
    if trend == "down":
        return current_price >= lo_f
    return None


def _candidate_new_move_active(new_move: dict[str, Any] | None) -> bool:
    if not new_move:
        return False
    legs = new_move.get("legs") or []
    return any(isinstance(l, dict) and bool(l.get("confirmed")) for l in legs)


def get_stored_candidate_impulse(symbol: str, db: Session) -> CandidateImpulseCache | None:
    sym = symbol.strip().upper()
    return (
        db.query(CandidateImpulseCache)
        .filter(CandidateImpulseCache.symbol == sym)
        .one_or_none()
    )


def _last_global_bos_price(legs: list[dict[str, Any]] | None) -> float | None:
    for leg in reversed(legs or []):
        if not isinstance(leg, dict):
            continue
        if leg.get("type") == "impulse" and leg.get("confirmed") and leg.get("end_price") is not None:
            try:
                return float(leg["end_price"])
            except (TypeError, ValueError):
                return None
    return None


def _build_candidate_from_cache(
    candidate_cache: CandidateImpulseCache,
    chart_candles: list,
    global_trend: str,
    reference_bos_price: float | None,
) -> dict[str, Any] | None:
    if candidate_cache is None:
        return None

    start_ts = candidate_cache.start_timestamp
    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)
    pivot_idx = _nearest_candle_index(chart_candles, start_ts) if chart_candles else None

    candidate_legs_raw = list(candidate_cache.legs_json or [])
    candidate_legs: list[dict[str, Any]] = []
    for leg in candidate_legs_raw:
        if not isinstance(leg, dict):
            continue
        enriched = dict(leg)
        enriched["render_style"] = "candidate"
        candidate_legs.append(enriched)
    candidate_bos_levels = list(candidate_cache.bos_levels_json or [])
    candidate_choch_zone = candidate_cache.choch_zone_json if isinstance(candidate_cache.choch_zone_json, dict) else None
    candidate_prime_impulse = (
        copy.deepcopy(candidate_cache.prime_impulse_json)
        if isinstance(candidate_cache.prime_impulse_json, dict)
        else None
    )
    candidate_prime_choch_zone = candidate_cache.prime_choch_zone_json if isinstance(candidate_cache.prime_choch_zone_json, dict) else None
    if isinstance(candidate_prime_impulse, dict) and candidate_prime_choch_zone is not None:
        candidate_prime_impulse.setdefault("choch_zone", copy.deepcopy(candidate_prime_choch_zone))

    confirmed_count = sum(
        1 for leg in candidate_legs if isinstance(leg, dict) and bool(leg.get("confirmed"))
    )
    last_confirmed = None
    for leg in reversed(candidate_legs):
        if isinstance(leg, dict) and leg.get("confirmed"):
            last_confirmed = leg
            break
    candidate_phase = str(last_confirmed.get("type")) if isinstance(last_confirmed, dict) and last_confirmed.get("type") else None

    current_price = float(chart_candles[-1].close) if chart_candles else None
    candidate_ichoch = None
    if current_price is not None and candidate_prime_choch_zone:
        candidate_ichoch = _candidate_ichoch_reached(global_trend, {"internal_choch_zone": candidate_prime_choch_zone}, current_price)

    teal_structure = {
        "legs": candidate_legs,
        "bos_levels": candidate_bos_levels,
        "global_choch_zone": candidate_choch_zone,
        "internal_choch_zone": candidate_prime_choch_zone,
        "render_style": "candidate",
    }
    if teal_structure and teal_structure.get("legs"):
        teal_structure = {
            **teal_structure,
            "legs": [
                {**leg, "render_style": "candidate"}
                for leg in teal_structure["legs"]
            ],
        }

    return {
        "pivot_index": pivot_idx,
        "pivot_price": float(candidate_cache.start_price),
        "move_start_timestamp": start_ts.isoformat(),
        "reference_bos_price": reference_bos_price,
        "reference_bos_start_index": None,
        "structure_broken": candidate_cache.structure_broken,
        "teal_structure": teal_structure,
        "candidate_ichoch_reached": candidate_ichoch,
        "candidate_new_move_active": confirmed_count >= 2,
        "candidate_legs": candidate_legs,
        "candidate_bos_levels": candidate_bos_levels,
        "candidate_choch_zone": candidate_choch_zone,
        "candidate_prime_impulse": candidate_prime_impulse,
        "candidate_prime_choch_zone": candidate_prime_choch_zone,
        "candidate_walker": candidate_cache.candidate_walker_json,
        "choch_source": candidate_cache.choch_source,
        "trend": global_trend,
        "phase": candidate_phase,
    }


def _build_candidate_move_attachment(
    candles: list,
    result: dict[str, Any],
    serialized: dict[str, Any],
    filter_config: dict[str, Any],
    symbol: str,
    new_move: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """CHoCH candidate pivot + sub-trend stack on slice (teal overlays) + structure_broken vs reference BOS."""
    trend = result.get("trend")
    if trend not in ("up", "down"):
        return None
    gz = serialized.get("global_choch_zone")
    iz = serialized.get("internal_choch_zone")
    legs_raw = result.get("legs") or []
    last_impulse = None
    for leg in reversed(legs_raw):
        if leg.get("type") == "impulse" and leg.get("confirmed"):
            last_impulse = leg
            break
    if last_impulse is None:
        return None
    min_swing = int(filter_config.get("min_swing_candles", 3))
    retr = _last_confirmed_retracement_leg(legs_raw)
    pivot_idx: int | None = None
    pivot_price: float | None = None
    move_start_ts: str | None = None
    if retr is not None:
        try:
            ri = int(retr["end_index"])
            pivot_price = float(retr["end_price"])
        except (TypeError, ValueError, KeyError):
            ri = -1
            pivot_price = None
        n_c = len(candles)
        if pivot_price is not None and 0 <= ri < n_c:
            pivot_idx = ri
            move_start_ts = candles[ri].timestamp.isoformat()
        else:
            pivot_idx = None
            pivot_price = None
            move_start_ts = None
    if pivot_idx is None:
        found = find_candidate_pivot_index(
            candles,
            trend,
            gz,
            iz,
            last_impulse,
            min_swing_candles=min_swing,
        )
        if found is None:
            return None
        pivot_idx = found
        pivot_candle = candles[pivot_idx]
        pivot_price = float(pivot_candle.low if trend == "up" else pivot_candle.high)
        move_start_ts = pivot_candle.timestamp.isoformat()
    ref = reference_bos_before_pivot(legs_raw, pivot_idx)
    last_close = float(candles[-1].close)
    if ref is None:
        structure_broken: bool | None = None
        ref_price = None
        ref_start_idx = None
    else:
        ref_price, ref_start_idx = ref
        structure_broken = structure_broken_from_close(trend, last_close, ref_price)
    slice_candles = candles[pivot_idx:]
    teal_structure: dict[str, Any] | None = None
    if len(slice_candles) >= 10:
        sub = identify_trend(slice_candles, **filter_config)
        if sub.get("trend") == "range":
            sub = identify_trend(
                slice_candles,
                trend_confirmation_pct=0.005,
                **_trend_kw_without_tcp(filter_config),
            )
        if sub.get("trend") != "range":
            compute_internal_structure(slice_candles, sub["legs"], **filter_config)
            apply_tf_deepening_to_legs(slice_candles, sub["legs"], filter_config, symbol)
            compute_internal_structure_levels(slice_candles, sub["legs"])
            teal_structure = _serialize_trend_legs_structure(
                slice_candles,
                sub,
                None,
                structure_color_override=STRUCTURE_CANDIDATE_MOVE_COLOR,
            )
    return {
        "pivot_index": pivot_idx,
        "pivot_price": pivot_price,
        "move_start_timestamp": move_start_ts,
        "reference_bos_price": ref_price,
        "reference_bos_start_index": ref_start_idx,
        "structure_broken": structure_broken,
        "teal_structure": teal_structure,
        "candidate_ichoch_reached": _candidate_ichoch_reached(trend, teal_structure, last_close),
        "candidate_new_move_active": _candidate_new_move_active(new_move),
    }


@universe_router.get("/stats")
def get_universe_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    setups = db.query(MonitoredSetup).all()

    by_category: dict[str, dict[str, int]] = {
        "crypto": {"count": 0, "trending_up": 0, "trending_down": 0},
        "forex": {"count": 0, "trending_up": 0, "trending_down": 0},
        "commodity": {"count": 0, "trending_up": 0, "trending_down": 0},
        "synthetic": {"count": 0, "trending_up": 0, "trending_down": 0},
    }
    by_phase = {"impulse": 0, "retracement": 0, "range": 0}
    by_depth = {"depth_1": 0, "depth_2": 0, "depth_3": 0}

    for setup in setups:
        category = _infer_category(setup.symbol)
        trend = (setup.htf_trend_direction or "").lower()
        if category in by_category:
            by_category[category]["count"] += 1
            if trend == "up":
                by_category[category]["trending_up"] += 1
            elif trend == "down":
                by_category[category]["trending_down"] += 1

        phase = (setup.current_phase or "range").lower()
        if phase not in {"impulse", "retracement", "range"}:
            phase = "range"
        by_phase[phase] += 1

        state = _parse_state(setup.structural_state_json)
        max_depth = int(state.get("max_depth_reached", 0) or 0)
        if max_depth == 1:
            by_depth["depth_1"] += 1
        elif max_depth == 2:
            by_depth["depth_2"] += 1
        elif max_depth >= 3:
            by_depth["depth_3"] += 1

    return {
        "total_monitored": len(setups),
        "by_category": by_category,
        "by_phase": by_phase,
        "by_depth": by_depth,
    }


@router.get("/{symbol}/move")
def get_move_analysis(
    symbol: str,
    start: str,
    end: str | None = None,
    timeframe: str = "auto",
) -> dict[str, Any]:
    symbol_upper = symbol.upper()

    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid start: {exc}") from exc

    if end is None:
        end_dt = datetime.now(timezone.utc)
    else:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid end: {exc}") from exc

    is_binance = symbol_upper.endswith("USDT") or symbol_upper.endswith("BTC")

    auto_tf_order = ["4h", "1h", "15m", "5m"]
    min_legs = 3

    def _fetch_slice(tf: str) -> list:
        if is_binance:
            all_candles = fetch_binance_ohlc_sync(symbol_upper, tf, start_time=start_dt)
        elif is_yfinance_symbol(symbol_upper):
            all_candles = fetch_yfinance_ohlc_sync(symbol_upper, tf, start_time=start_dt)
        else:
            all_candles = fetch_deriv_ohlc_sync(symbol_upper, tf, start_time=start_dt)
        return [c for c in all_candles if start_dt <= c.timestamp <= end_dt]

    def _analyze(candles: list) -> dict:
        result = identify_trend(candles, **FILTER_CONFIG)
        compute_internal_structure(candles, result["legs"], **FILTER_CONFIG)
        return result

    def _count_confirmed(result: dict) -> int:
        outer = [l for l in result["legs"] if l.get("confirmed")]
        internal = [
            il
            for l in result["legs"]
            for il in (l.get("internal_structure") or {}).get("legs", [])
            if il.get("confirmed")
        ]
        return len(outer) + len(internal)

    selected_tf: str | None = None
    selected_candles: list | None = None
    selected_result: dict | None = None

    if timeframe == "auto":
        for tf in auto_tf_order:
            try:
                tf_candles = _fetch_slice(tf)
            except Exception:
                continue
            if len(tf_candles) < 100:
                continue
            tf_result = _analyze(tf_candles)
            if _count_confirmed(tf_result) >= min_legs:
                selected_tf = tf
                selected_candles = tf_candles
                selected_result = tf_result
                break
        if selected_tf is None:
            raise HTTPException(
                status_code=422,
                detail="No timeframe found 3+ confirmed legs. Widen the date range or lower MIN_LEGS.",
            )
    else:
        try:
            selected_candles = _fetch_slice(timeframe)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Fetch failed: {exc}") from exc
        if not selected_candles:
            raise HTTPException(status_code=422, detail="No candles in the specified range.")
        selected_tf = timeframe
        selected_result = _analyze(selected_candles)

    try:
        state_report = walk_structure(
            selected_candles,
            selected_result,
            FILTER_CONFIG,
            max_depth=3,
            symbol=symbol_upper,
        )
        structural_state = serialize_state_report(state_report)
    except Exception:
        structural_state = {}

    confirmed_legs = [
        {
            "type": leg["type"],
            "start_price": leg["start_price"],
            "end_price": leg["end_price"],
            "start_index": leg["start_index"],
            "end_index": leg["end_index"],
            "confirmed": leg["confirmed"],
        }
        for leg in selected_result["legs"]
        if leg.get("confirmed")
    ]

    return {
        "symbol": symbol_upper,
        "timeframe_used": selected_tf,
        "candle_count": len(selected_candles),
        "trend": selected_result["trend"],
        "current_phase": selected_result["current_phase"],
        "confirmed_legs": confirmed_legs,
        "structural_state": structural_state,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


@router.get("/{symbol}/signals")
def get_signal_history(
    symbol: str,
    timeframe: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    q = (
        db.query(SignalHistory)
        .filter(SignalHistory.symbol == normalized)
        .order_by(SignalHistory.emitted_at.desc().id.desc())
    )
    if timeframe:
        q = q.filter(SignalHistory.timeframe == timeframe)
    rows = q.limit(max(1, min(limit, 200))).all()
    return {
        "symbol": normalized,
        "items": [
            {
                "id": row.id,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "signal": row.signal,
                "trend_direction": row.trend_direction,
                "trend_score": row.trend_score,
                "emitted_at": row.emitted_at.isoformat() if row.emitted_at else None,
            }
            for row in rows
        ],
    }


def _compute_bos_classifications(
    structural_state: dict,
    candles: list,
    trend: str,
) -> dict[str, str]:
    classifications: dict[str, str] = {}
    levels = structural_state.get("levels") or []
    for level in levels:
        depth = level.get("depth", 1)
        struct_lvl = level.get("structural_level") or {}
        bos_price = struct_lvl.get("price")
        crossing = level.get("crossing_attempt") or {}

        if not bos_price or not candles:
            classifications[f"depth_{depth}"] = "pending"
            continue

        if not crossing:
            classifications[f"depth_{depth}"] = "pending"
            continue

        g_cross_end = crossing.get("global_end_index")
        if g_cross_end is None or g_cross_end >= len(candles):
            classifications[f"depth_{depth}"] = "pending"
            continue

        post_candles = candles[int(g_cross_end):]
        bos_price_f = float(bos_price)

        price_returned = any(
            (trend == "up" and c.high > bos_price_f) or
            (trend == "down" and c.low < bos_price_f)
            for c in post_candles
        )

        if price_returned:
            classifications[f"depth_{depth}"] = "false"
        elif len(post_candles) > 3:
            classifications[f"depth_{depth}"] = "true"
        else:
            classifications[f"depth_{depth}"] = "pending"

    return classifications


def _attach_level_start_timestamps(
    structural_state: dict[str, Any],
    candles: list,
) -> None:
    """Attach level.start_timestamp from first_impulse_global_start for chart anchoring."""
    if not structural_state or not candles:
        return
    levels = structural_state.get("levels")
    if not isinstance(levels, list):
        return
    n = len(candles)
    for level in levels:
        if not isinstance(level, dict):
            continue
        if level.get("start_timestamp"):
            continue
        g_start = level.get("first_impulse_global_start")
        if g_start is not None and 0 <= int(g_start) < n:
            level["start_timestamp"] = candles[int(g_start)].timestamp.isoformat()
        else:
            level["start_timestamp"] = candles[0].timestamp.isoformat()


def _get_open_paper_trade(
    symbol: str,
    db: Session,
) -> dict | None:
    trade = (
        db.query(PaperTrade)
        .filter(
            PaperTrade.symbol == symbol,
            PaperTrade.status == "open",
        )
        .first()
    )
    if trade is None:
        return None
    return {
        "entry_price": trade.entry_price,
        "stop_price": trade.stop_price,
        "take_profit_price": trade.take_profit_price,
        "direction": trade.direction,
        "status": trade.status,
    }


def _get_active_overrides(
    symbol: str,
    db: Session,
) -> dict[str, dict]:
    """
    Return active manual overrides for symbol as a dict keyed by override_type.
    Example: {"global_choch": {...}, "ichoch": {...}}
    """
    rows = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == symbol,
            ManualStructureOverride.is_active.is_(True),
        )
        .all()
    )
    result: dict[str, dict] = {}
    for row in rows:
        result[row.override_type] = {
            "lower_boundary": row.lower_boundary,
            "upper_boundary": row.upper_boundary,
            "start_timestamp": row.start_timestamp.isoformat()
            if row.start_timestamp else None,
            "end_timestamp": row.end_timestamp.isoformat()
            if row.end_timestamp else None,
            "trend_start_timestamp":
                row.trend_start_timestamp.isoformat()
                if row.trend_start_timestamp else None,
            "trend_end_timestamp":
                row.trend_end_timestamp.isoformat()
                if row.trend_end_timestamp else None,
            "depth_index": row.depth_index,
        }
    return result


def _params_hash(params: dict) -> str:
    """Hash analysis params for cache invalidation when settings change."""
    serialized = _json.dumps(params, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode()).hexdigest()[:16]


def _get_cached_analysis(
    symbol: str,
    timeframe: str,
    params: dict,
    db: Session,
) -> dict | None:
    """Return cached analysis result when valid.

    Cache is considered valid when a row exists for ``symbol+timeframe``,
    the params hash matches the request, and the row is younger than
    ``ttl_seconds``. Any other condition is a miss (returns ``None``).
    """
    row = (
        db.query(AnalysisResultCache)
        .filter(
            AnalysisResultCache.symbol == symbol.strip().upper(),
            AnalysisResultCache.timeframe == timeframe.lower(),
        )
        .first()
    )
    if row is None:
        return None

    current_hash = _params_hash(params)
    if row.params_hash != current_hash:
        logger.debug(
            "Analysis cache miss (params changed) %s %s",
            symbol,
            timeframe,
        )
        return None

    computed_at = row.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - computed_at).total_seconds()
    if age > row.ttl_seconds:
        logger.debug(
            "Analysis cache miss (expired %ds) %s %s",
            int(age),
            symbol,
            timeframe,
        )
        return None

    logger.debug(
        "Analysis cache hit %s %s (age=%ds)",
        symbol,
        timeframe,
        int(age),
    )
    cached = dict(row.result_json)
    cached["analysis_is_cached"] = True
    cached["analysis_cache_age_seconds"] = int(age)
    cached["analysis_computed_at"] = (
        row.computed_at.isoformat() if row.computed_at else None
    )
    return cached


def _write_analysis_cache(
    symbol: str,
    timeframe: str,
    params: dict,
    result: dict,
    db: Session,
    ttl_seconds: int = 14400,
) -> None:
    """Write or update the analysis result cache for ``symbol+timeframe``."""
    sym = symbol.strip().upper()
    tf = timeframe.lower()
    phash = _params_hash(params)
    now = datetime.now(timezone.utc)

    existing = (
        db.query(AnalysisResultCache)
        .filter(
            AnalysisResultCache.symbol == sym,
            AnalysisResultCache.timeframe == tf,
        )
        .first()
    )

    if existing is None:
        db.add(
            AnalysisResultCache(
                symbol=sym,
                timeframe=tf,
                result_json=result,
                params_hash=phash,
                computed_at=now,
                ttl_seconds=ttl_seconds,
            )
        )
    else:
        existing.result_json = result
        existing.params_hash = phash
        existing.computed_at = now
        existing.ttl_seconds = ttl_seconds

    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to write analysis cache %s %s: %s", sym, tf, e
        )
        db.rollback()


def _invalidate_analysis_cache(
    symbol: str,
    db: Session,
) -> None:
    """Remove all cached analysis rows for ``symbol``.

    Call this when the structure a row was computed from has changed:
    rank universe rewriting the symbol, a manual override save, or any
    explicit parameter change that must force a recompute.
    """
    sym = symbol.strip().upper()
    db.query(AnalysisResultCache).filter(
        AnalysisResultCache.symbol == sym
    ).delete()
    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("Cache invalidation failed %s: %s", sym, e)


def on_structure_updated(
    symbol: str,
    db: Session,
) -> None:
    """
    Centralized hook called whenever structure
    is successfully recomputed for a symbol.

    Every code path that updates global structure,
    score, or market state MUST call this function
    instead of calling _invalidate_analysis_cache
    directly.

    Currently handles:
    - Analysis result cache invalidation

    Future hooks can be added here without
    touching every call site.
    """
    try:
        _invalidate_analysis_cache(symbol, db)
        logger.debug(
            "on_structure_updated: cache cleared "
            "for %s", symbol
        )
    except Exception as e:
        logger.warning(
            "on_structure_updated failed for "
            "%s: %s", symbol, e
        )


@router.get("/{symbol}")
def get_analysis(
    symbol: str,
    timeframe: str = "1h",
    db: Session = Depends(get_db),
    min_swing_candles: int | None = Query(default=None),
    trend_confirmation_pct: float | None = Query(default=None),
    use_parent_relative_filter: bool | None = Query(default=None),
    min_impulse_parent_ratio: float | None = Query(default=None),
    use_momentum_filter: bool | None = Query(default=None),
    min_momentum_ratio: float | None = Query(default=None),
    use_dominance_filter: bool | None = Query(default=None),
    min_dominance_ratio: float | None = Query(default=None),
    max_walk_depth: int | None = Query(default=None),
    rmt_use_parent_relative_filter: bool | None = Query(default=None),
    rmt_min_impulse_parent_ratio: float | None = Query(default=None),
    rmt_use_momentum_filter: bool | None = Query(default=None),
    rmt_min_momentum_ratio: float | None = Query(default=None),
    rmt_use_dominance_filter: bool | None = Query(default=None),
    rmt_min_dominance_ratio: float | None = Query(default=None),
) -> dict[str, Any]:
    _validate_trend_query_params(
        min_swing_candles=min_swing_candles,
        trend_confirmation_pct=trend_confirmation_pct,
        min_impulse_parent_ratio=min_impulse_parent_ratio,
        min_momentum_ratio=min_momentum_ratio,
        min_dominance_ratio=min_dominance_ratio,
        max_walk_depth=max_walk_depth,
        rmt_min_impulse_parent_ratio=rmt_min_impulse_parent_ratio,
        rmt_min_momentum_ratio=rmt_min_momentum_ratio,
        rmt_min_dominance_ratio=rmt_min_dominance_ratio,
    )

    symbol_upper = symbol.upper()
    timeframe_lower = timeframe.lower()

    analysis_cache_params = _analysis_cache_params_for_hash(
        min_swing_candles=min_swing_candles,
        trend_confirmation_pct=trend_confirmation_pct,
        use_parent_relative_filter=use_parent_relative_filter,
        min_impulse_parent_ratio=min_impulse_parent_ratio,
        use_momentum_filter=use_momentum_filter,
        min_momentum_ratio=min_momentum_ratio,
        use_dominance_filter=use_dominance_filter,
        min_dominance_ratio=min_dominance_ratio,
        max_walk_depth=max_walk_depth,
        rmt_use_parent_relative_filter=rmt_use_parent_relative_filter,
        rmt_min_impulse_parent_ratio=rmt_min_impulse_parent_ratio,
        rmt_use_momentum_filter=rmt_use_momentum_filter,
        rmt_min_momentum_ratio=rmt_min_momentum_ratio,
        rmt_use_dominance_filter=rmt_use_dominance_filter,
        rmt_min_dominance_ratio=rmt_min_dominance_ratio,
    )

    # Cache short-circuit: the 4-hour refresh job (and the first miss) writes
    # the full response here. All other requests read from cache so opening a
    # market view is instant after the first compute.
    cached = _get_cached_analysis(
        symbol_upper, timeframe_lower, analysis_cache_params, db
    )
    if cached is not None:
        return cached

    trend_kw = _merge_trend_filter_kwargs(
        min_swing_candles=min_swing_candles,
        trend_confirmation_pct=trend_confirmation_pct,
        use_parent_relative_filter=use_parent_relative_filter,
        min_impulse_parent_ratio=min_impulse_parent_ratio,
        use_momentum_filter=use_momentum_filter,
        min_momentum_ratio=min_momentum_ratio,
        use_dominance_filter=use_dominance_filter,
        min_dominance_ratio=min_dominance_ratio,
    )
    rmt_kw = _merge_rmt_filter_kwargs(
        rmt_use_parent_relative_filter=rmt_use_parent_relative_filter,
        rmt_min_impulse_parent_ratio=rmt_min_impulse_parent_ratio,
        rmt_use_momentum_filter=rmt_use_momentum_filter,
        rmt_min_momentum_ratio=rmt_min_momentum_ratio,
        rmt_use_dominance_filter=rmt_use_dominance_filter,
        rmt_min_dominance_ratio=rmt_min_dominance_ratio,
    )
    walk_depth = _DEFAULT_WALK_DEPTH if max_walk_depth is None else max_walk_depth
    walk_extras: dict[str, Any] = {"max_depth": walk_depth}
    if rmt_kw is not None:
        walk_extras["rmt_filter_config"] = rmt_kw

    setup = (
        db.query(MonitoredSetup)
        .filter(MonitoredSetup.symbol == symbol_upper)
        .order_by(MonitoredSetup.trend_score.desc(), MonitoredSetup.id.asc())
        .first()
    )
    if setup is None:
        try:
            candles = _get_candles_from_store(db, symbol_upper, timeframe_lower)
        except HTTPException:
            raise

        if not candles:
            raise HTTPException(
                status_code=422,
                detail=f"No candles returned for symbol={symbol_upper} timeframe={timeframe_lower}",
            )

        cache_bundle = _try_global_cache_result(symbol_upper, db, candles)
        if cache_bundle is None:
            return {
                "status": "not_found",
                "symbol": symbol_upper,
                "open_paper_trade": _get_open_paper_trade(symbol_upper, db),
            }

        result, ref_candles, gsc = cache_bundle
        confirmed_impulses = [
            l for l in result.get("legs", [])
            if l.get("type") == "impulse" and l.get("confirmed")
            and l.get("internal_structure") is not None
        ]
        _did_compute_internal = not confirmed_impulses
        if not confirmed_impulses:
            compute_internal_structure(candles, result["legs"], **trend_kw)
        _stored_walker_exists = get_stored_walker(symbol_upper, db) is not None
        if not _stored_walker_exists:
            _enrich_internal_structure_with_tf_deepening(
                candles, result["legs"], trend_kw, symbol_upper
            )
        if _did_compute_internal:
            compute_internal_structure_levels(candles, result["legs"])

        stored_walk = _try_stored_walker_json(
            db, symbol_upper, timeframe_lower, rmt_kw, walk_depth
        )
        if stored_walk is not None:
            state = stored_walk
            state_report = state
        else:
            state_report = walk_structure(
                candles,
                result,
                trend_kw,
                symbol=symbol_upper,
                **walk_extras,
            )
            state = serialize_state_report(state_report)
        _attach_level_start_timestamps(state, candles)

        if _stored_walker_exists:
            new_move = None
        else:
            new_move = _compute_new_move_analysis(
                candles, state_report, symbol_upper, trend_kw
            )

        prime_kw = _prime_serializer_kwargs(symbol_upper, db)
        leg_payload = _serialize_trend_legs_structure(
            candles,
            result,
            state,
            cached_globals=True,
            bos_raw_cached=gsc.bos_levels_json or [],
            choch_level_cached=gsc.choch_level_json,
            global_choch_zone_cached=gsc.choch_zone_json,
            ref_candles=ref_candles,
            **prime_kw,
        )

        candidate_cache = get_stored_candidate_impulse(symbol_upper, db)
        if candidate_cache is not None:
            candidate_move = _build_candidate_from_cache(
                candidate_cache,
                candles,
                str(gsc.trend_direction or result.get("trend") or "range"),
                _last_global_bos_price(gsc.legs_json or result.get("legs") or []),
            )
        elif not _stored_walker_exists:
            candidate_move = _build_candidate_move_attachment(
                candles,
                result,
                leg_payload,
                trend_kw,
                symbol_upper,
                new_move=new_move,
            )
        else:
            candidate_move = None

        max_depth_reached = int(state.get("max_depth_reached", 0) or 0)
        total_mitigation_count = int(state.get("total_mitigation_count", 0) or 0)
        waiting_for = state.get("waiting_for", "")
        prime_impulse_structure = None
        if prime_kw.get("prime_legs_json"):
            prime_impulse_structure = {
                "legs": prime_kw["prime_legs_json"],
                "source_tf": prime_kw.get("prime_source_tf"),
                "choch_zone": prime_kw.get("prime_choch_zone_json"),
            }
        bos_classifications = _compute_bos_classifications(
            state, candles, str(gsc.trend_direction or result.get("trend") or "up")
        )

        result_dict = {
            "status": "ok",
            "symbol": symbol_upper,
            "timeframe": timeframe_lower,
            "global_trend": gsc.trend_direction,
            "reference_timeframe": gsc.reference_timeframe,
            "max_depth_reached": max_depth_reached,
            "total_mitigation_count": total_mitigation_count,
            "waiting_for": waiting_for,
            "structural_state": state,
            "new_move": new_move,
            "live_computed": False,
            "candidate_move": candidate_move,
            "prime_impulse_structure": prime_impulse_structure,
            "bos_classifications": bos_classifications,
            "market_state": (gsc.market_state if gsc is not None else "WAITING"),
            "open_paper_trade": _get_open_paper_trade(symbol_upper, db),
            "manual_overrides": _get_active_overrides(symbol_upper, db),
            "layer_cache_timestamps": _layer_cache_timestamps(
                symbol_upper,
                db,
                gsc=gsc,
                pis=get_stored_prime_impulse_structure(symbol_upper, db),
                walker=get_stored_walker(symbol_upper, db),
                candidate=candidate_cache,
            ),
            **leg_payload,
        }
        result_dict["analysis_is_cached"] = False
        result_dict["analysis_cache_age_seconds"] = 0
        result_dict["analysis_computed_at"] = datetime.now(timezone.utc).isoformat()
        _write_analysis_cache(
            symbol_upper, timeframe_lower, analysis_cache_params, result_dict, db
        )
        return result_dict

    stored_tf = (setup.htf_timeframe or "").lower()
    if timeframe_lower == stored_tf:
        setup_state = _parse_state(setup.structural_state_json)
        global_trend = setup_state.get("global_trend", setup.htf_trend_direction or "range")

        fetch_tf = stored_tf or timeframe_lower
        try:
            leg_candles = _get_candles_from_store(db, symbol_upper, fetch_tf)
        except HTTPException:
            raise
        if not leg_candles:
            raise HTTPException(
                status_code=422,
                detail=f"No candles for legs refetch symbol={symbol_upper} timeframe={fetch_tf}",
            )
        cache_bundle = _try_global_cache_result(symbol_upper, db, leg_candles)
        if cache_bundle is not None:
            leg_result, ref_candles, gsc = cache_bundle
            global_trend = gsc.trend_direction
        else:
            leg_result = identify_trend(leg_candles, **trend_kw)
            ref_candles = []
        confirmed_impulses = (
            [
                l for l in leg_result.get("legs", [])
                if l.get("type") == "impulse" and l.get("confirmed")
                and l.get("internal_structure") is not None
            ]
            if cache_bundle is not None
            else []
        )
        _did_compute_internal = not confirmed_impulses
        if not confirmed_impulses:
            compute_internal_structure(leg_candles, leg_result["legs"], **trend_kw)
        _stored_walker_exists = get_stored_walker(symbol_upper, db) is not None
        if not _stored_walker_exists:
            _enrich_internal_structure_with_tf_deepening(
                leg_candles, leg_result["legs"], trend_kw, symbol_upper
            )
        if _did_compute_internal:
            compute_internal_structure_levels(leg_candles, leg_result["legs"])
        stored_walk = _try_stored_walker_json(
            db, symbol_upper, fetch_tf.lower(), rmt_kw, walk_depth
        )
        if stored_walk is not None:
            state = stored_walk
            state_report: dict[str, Any] = state
        else:
            state_report = walk_structure(
                leg_candles,
                leg_result,
                trend_kw,
                symbol=symbol_upper,
                **walk_extras,
            )
            state = serialize_state_report(state_report)
        _attach_level_start_timestamps(state, leg_candles)
        max_depth_reached = int(state.get("max_depth_reached", 0) or 0)
        total_mitigation_count = int(state.get("total_mitigation_count", 0) or 0)
        waiting_for = state.get("waiting_for", "")
        if _stored_walker_exists:
            new_move = None
        else:
            new_move = _compute_new_move_analysis(
                leg_candles, state_report, symbol_upper, trend_kw
            )
        prime_kw = _prime_serializer_kwargs(symbol_upper, db)
        if cache_bundle is not None:
            leg_payload = _serialize_trend_legs_structure(
                leg_candles,
                leg_result,
                state,
                cached_globals=True,
                bos_raw_cached=gsc.bos_levels_json or [],
                choch_level_cached=gsc.choch_level_json,
                global_choch_zone_cached=gsc.choch_zone_json,
                ref_candles=ref_candles,
                **prime_kw,
            )
        else:
            leg_payload = _serialize_trend_legs_structure(
                leg_candles, leg_result, state, **prime_kw
            )
        candidate_cache = get_stored_candidate_impulse(symbol_upper, db)
        if candidate_cache is not None:
            candidate_move = _build_candidate_from_cache(
                candidate_cache,
                leg_candles,
                str(global_trend or leg_result.get("trend") or "range"),
                _last_global_bos_price(
                    (cache_bundle[2].legs_json if cache_bundle is not None else leg_result.get("legs")) or []
                ),
            )
        elif _stored_walker_exists:
            candidate_move = None
        else:
            candidate_move = _build_candidate_move_attachment(
                leg_candles,
                leg_result,
                leg_payload,
                trend_kw,
                symbol_upper,
                new_move=new_move,
            )

        reference_timeframe = (
            cache_bundle[2].reference_timeframe if cache_bundle is not None else None
        )
        prime_impulse_structure = None
        if prime_kw.get("prime_legs_json"):
            prime_impulse_structure = {
                "legs": prime_kw["prime_legs_json"],
                "source_tf": prime_kw.get("prime_source_tf"),
                "choch_zone": prime_kw.get("prime_choch_zone_json"),
            }
        bos_classifications = _compute_bos_classifications(
            state, leg_candles, str(global_trend or "up")
        )

        result_dict = {
            "status": "ok",
            "symbol": symbol_upper,
            "timeframe": setup.htf_timeframe,
            "global_trend": global_trend,
            "reference_timeframe": reference_timeframe,
            "max_depth_reached": max_depth_reached,
            "total_mitigation_count": total_mitigation_count,
            "waiting_for": waiting_for,
            "structural_state": state,
            "new_move": new_move,
            "live_computed": False,
            "candidate_move": candidate_move,
            "prime_impulse_structure": prime_impulse_structure,
            "bos_classifications": bos_classifications,
            "market_state": (cache_bundle[2].market_state if cache_bundle is not None else "WAITING"),
            "open_paper_trade": _get_open_paper_trade(symbol_upper, db),
            "manual_overrides": _get_active_overrides(symbol_upper, db),
            "layer_cache_timestamps": _layer_cache_timestamps(
                symbol_upper,
                db,
                gsc=(cache_bundle[2] if cache_bundle is not None else None),
                pis=get_stored_prime_impulse_structure(symbol_upper, db),
                walker=get_stored_walker(symbol_upper, db),
                candidate=candidate_cache,
            ),
            **leg_payload,
        }
        result_dict["analysis_is_cached"] = False
        result_dict["analysis_cache_age_seconds"] = 0
        result_dict["analysis_computed_at"] = datetime.now(timezone.utc).isoformat()
        _write_analysis_cache(
            symbol_upper, timeframe_lower, analysis_cache_params, result_dict, db
        )
        return result_dict

    try:
        candles = _get_candles_from_store(db, symbol_upper, timeframe_lower)
    except HTTPException:
        raise

    if not candles:
        raise HTTPException(
            status_code=422,
            detail=f"No candles returned for symbol={symbol_upper} timeframe={timeframe_lower}",
        )

    cache_bundle = _try_global_cache_result(symbol_upper, db, candles)
    if cache_bundle is not None:
        result, ref_candles, gsc = cache_bundle
    else:
        result = identify_trend(candles, **trend_kw)
        ref_candles = []
    confirmed_impulses = (
        [
            l for l in result.get("legs", [])
            if l.get("type") == "impulse" and l.get("confirmed")
            and l.get("internal_structure") is not None
        ]
        if cache_bundle is not None
        else []
    )
    _did_compute_internal = not confirmed_impulses
    if not confirmed_impulses:
        compute_internal_structure(candles, result["legs"], **trend_kw)
    _stored_walker_exists = get_stored_walker(symbol_upper, db) is not None
    if not _stored_walker_exists:
        _enrich_internal_structure_with_tf_deepening(
            candles, result["legs"], trend_kw, symbol_upper
        )
    if _did_compute_internal:
        compute_internal_structure_levels(candles, result["legs"])
    stored_walk = _try_stored_walker_json(
        db, symbol_upper, timeframe_lower, rmt_kw, walk_depth
    )
    if stored_walk is not None:
        state = stored_walk
        state_report = state
    else:
        state_report = walk_structure(
            candles,
            result,
            trend_kw,
            symbol=symbol_upper,
            **walk_extras,
        )
        state = serialize_state_report(state_report)
    _attach_level_start_timestamps(state, candles)
    if _stored_walker_exists:
        new_move = None
    else:
        new_move = _compute_new_move_analysis(
            candles, state_report, symbol_upper, trend_kw
        )
    prime_kw = _prime_serializer_kwargs(symbol_upper, db)
    if cache_bundle is not None:
        leg_payload = _serialize_trend_legs_structure(
            candles,
            result,
            state,
            cached_globals=True,
            bos_raw_cached=gsc.bos_levels_json or [],
            choch_level_cached=gsc.choch_level_json,
            global_choch_zone_cached=gsc.choch_zone_json,
            ref_candles=ref_candles,
            **prime_kw,
        )
        global_trend = gsc.trend_direction
    else:
        leg_payload = _serialize_trend_legs_structure(candles, result, state, **prime_kw)
        global_trend = state.get("global_trend", result.get("trend", "range"))
    candidate_cache = get_stored_candidate_impulse(symbol_upper, db)
    if candidate_cache is not None:
        candidate_move = _build_candidate_from_cache(
            candidate_cache,
            candles,
            str(global_trend or result.get("trend") or "range"),
            _last_global_bos_price(
                (cache_bundle[2].legs_json if cache_bundle is not None else result.get("legs")) or []
            ),
        )
    elif _stored_walker_exists:
        candidate_move = None
    else:
        candidate_move = _build_candidate_move_attachment(
            candles,
            result,
            leg_payload,
            trend_kw,
            symbol_upper,
            new_move=new_move,
        )
    max_depth_reached = int(state.get("max_depth_reached", 0) or 0)
    total_mitigation_count = int(state.get("total_mitigation_count", 0) or 0)
    waiting_for = state.get("waiting_for", "")

    reference_timeframe = (
        cache_bundle[2].reference_timeframe if cache_bundle is not None else None
    )
    prime_impulse_structure = None
    if prime_kw.get("prime_legs_json"):
        prime_impulse_structure = {
            "legs": prime_kw["prime_legs_json"],
            "source_tf": prime_kw.get("prime_source_tf"),
            "choch_zone": prime_kw.get("prime_choch_zone_json"),
        }
    bos_classifications = _compute_bos_classifications(
        state, candles, str(global_trend or "up")
    )

    result_dict = {
        "status": "ok",
        "symbol": symbol_upper,
        "timeframe": timeframe_lower,
        "global_trend": global_trend,
        "reference_timeframe": reference_timeframe,
        "max_depth_reached": max_depth_reached,
        "total_mitigation_count": total_mitigation_count,
        "waiting_for": waiting_for,
        "structural_state": state,
        "new_move": new_move,
        "live_computed": True,
        "candidate_move": candidate_move,
        "prime_impulse_structure": prime_impulse_structure,
        "bos_classifications": bos_classifications,
        "market_state": (cache_bundle[2].market_state if cache_bundle is not None else "WAITING"),
        "open_paper_trade": _get_open_paper_trade(symbol_upper, db),
        "manual_overrides": _get_active_overrides(symbol_upper, db),
        "layer_cache_timestamps": _layer_cache_timestamps(
            symbol_upper,
            db,
            gsc=(cache_bundle[2] if cache_bundle is not None else None),
            pis=get_stored_prime_impulse_structure(symbol_upper, db),
            walker=get_stored_walker(symbol_upper, db),
            candidate=candidate_cache,
        ),
        **leg_payload,
    }
    result_dict["analysis_is_cached"] = False
    result_dict["analysis_cache_age_seconds"] = 0
    result_dict["analysis_computed_at"] = datetime.now(timezone.utc).isoformat()
    _write_analysis_cache(
        symbol_upper, timeframe_lower, analysis_cache_params, result_dict, db
    )
    return result_dict