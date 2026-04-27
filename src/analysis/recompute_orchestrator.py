from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.analysis.override_resolver import (
    resolve_candidate_override,
    resolve_global_override,
    resolve_prime_override,
    resolve_walker_depth_override,
)
from src.cache import candle_store
from src.core.structure_levels import compute_all_structure_levels
from src.db.models import (
    CandidateImpulseCache,
    GlobalStructureCache,
    ManualStructureOverride,
    PrimeImpulseStructure,
    StoredWalkerResult,
)
from src.db.session import SessionLocal
from src.scanner.global_structure import (
    compute_candidate_impulse_for_symbol,
    compute_global_structure_for_symbol,
    compute_prime_impulse_structure,
    compute_walker_for_symbol,
    get_stored_global_structure,
    get_stored_walker,
)

logger = logging.getLogger(__name__)

_LAYER_ORDER = ["global", "prime", "walker", "candidate"]
_VALID_LAYERS = set(_LAYER_ORDER)


def _as_utc(dt) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _reference_tf_to_cache_tf(reference_timeframe: str | None) -> str:
    ref = (reference_timeframe or "").strip().lower()
    if ref == "weekly":
        return "1w"
    if ref == "daily":
        return "1d"
    return "1d"


def _confirmed_leg_count(legs: list[dict[str, Any]] | None) -> int:
    if not legs:
        return 0
    return sum(1 for leg in legs if isinstance(leg, dict) and leg.get("confirmed"))


def _last_confirmed_impulse(legs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for leg in reversed(legs or []):
        if not isinstance(leg, dict):
            continue
        if leg.get("type") == "impulse" and leg.get("confirmed"):
            return leg
    return None


def _largest_confirmed_impulse(legs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_move = -1.0
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        if leg.get("type") != "impulse" or not leg.get("confirmed"):
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _load_active_overrides(symbol: str, db: Session) -> tuple[dict[str, Any], dict[tuple[str, int], Any], list[str]]:
    sym = symbol.strip().upper()
    now = _now_utc()
    rows = (
        db.query(ManualStructureOverride)
        .filter(
            ManualStructureOverride.symbol == sym,
            ManualStructureOverride.is_active.is_(True),
            (ManualStructureOverride.expires_at.is_(None) | (ManualStructureOverride.expires_at > now)),
        )
        .all()
    )

    by_type: dict[str, Any] = {}
    depth_rows: dict[tuple[str, int], Any] = {}
    labels: list[str] = []

    for row in rows:
        ot = (row.override_type or "").strip().lower()
        if not ot:
            continue
        if ot == "depth_choch":
            if row.depth_index is None:
                continue
            depth_key = (ot, int(row.depth_index))
            depth_rows[depth_key] = row
            labels.append(f"depth_choch:{int(row.depth_index)}")
            continue
        by_type[ot] = row
        labels.append(ot)

    return by_type, depth_rows, labels


def _layers_from_cascade(by_type: dict[str, Any], depth_rows: dict[tuple[str, int], Any]) -> list[str]:
    if not by_type and not depth_rows:
        return list(_LAYER_ORDER)

    requested: set[str] = set()

    if "trend_bounds" in by_type or "global_choch" in by_type:
        requested.update({"global", "prime", "walker", "candidate"})

    if "ichoch" in by_type:
        requested.update({"prime", "walker", "candidate"})

    if depth_rows:
        requested.update({"walker", "candidate"})

    if "candidate_choch" in by_type or "candidate_ichoch" in by_type:
        requested.add("candidate")

    if not requested:
        return list(_LAYER_ORDER)

    return [layer for layer in _LAYER_ORDER if layer in requested]


def _normalize_explicit_layers(layers: list[str] | None) -> list[str] | None:
    if layers is None:
        return None
    normalized = {str(layer).strip().lower() for layer in layers}
    invalid = sorted(normalized - _VALID_LAYERS)
    if invalid:
        raise ValueError(f"Invalid layers: {invalid}. Valid values: {_LAYER_ORDER}")
    return [layer for layer in _LAYER_ORDER if layer in normalized]


def _upsert_global_from_resolver(symbol: str, db: Session, result: dict, reference_timeframe: str, candles: list) -> None:
    sym = symbol.strip().upper()
    trend_result = result["trend_result"]
    legs = trend_result.get("legs") or []
    levels = compute_all_structure_levels(candles, legs, trend_result.get("trend", "range"))

    row = db.query(GlobalStructureCache).filter(GlobalStructureCache.symbol == sym).one_or_none()
    payload = {
        "reference_timeframe": reference_timeframe,
        "confirmed_leg_count": _confirmed_leg_count(legs),
        "legs_json": _json_safe(legs),
        "bos_levels_json": _json_safe(levels.get("bos_levels") or []),
        "choch_zone_json": _json_safe(result.get("choch_zone")) if result.get("choch_zone") is not None else None,
        "choch_level_json": _json_safe(levels.get("choch_level")) if levels.get("choch_level") is not None else None,
        "trend_direction": trend_result.get("trend", "range"),
        "computed_at": _now_utc(),
        "candle_start_timestamp": _as_utc(getattr(candles[0], "timestamp", None)) if candles else None,
        "candle_end_timestamp": _as_utc(getattr(candles[-1], "timestamp", None)) if candles else None,
    }

    if row is None:
        row = GlobalStructureCache(symbol=sym, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)

    db.commit()


def _upsert_prime_from_resolver(
    symbol: str,
    db: Session,
    result: dict,
    source_timeframe: str,
    impulse_start_ts: datetime,
    impulse_end_ts: datetime,
    impulse_start_price: float,
    impulse_end_price: float,
    candles: list,
) -> None:
    sym = symbol.strip().upper()
    trend_result = result["trend_result"]
    legs = trend_result.get("legs") or []
    levels = compute_all_structure_levels(candles, legs, trend_result.get("trend", "range"))

    row = db.query(PrimeImpulseStructure).filter(PrimeImpulseStructure.symbol == sym).one_or_none()
    payload = {
        "source_timeframe": source_timeframe,
        "confirmed_leg_count": _confirmed_leg_count(legs),
        "legs_json": _json_safe(legs),
        "bos_levels_json": _json_safe(levels.get("bos_levels") or []),
        "choch_zone_json": _json_safe(result.get("choch_zone")) if result.get("choch_zone") is not None else None,
        "impulse_start_timestamp": impulse_start_ts,
        "impulse_end_timestamp": impulse_end_ts,
        "impulse_start_price": float(impulse_start_price),
        "impulse_end_price": float(impulse_end_price),
        "computed_at": _now_utc(),
    }

    if row is None:
        row = PrimeImpulseStructure(symbol=sym, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)

    db.commit()


def _apply_depth_override_zones_to_walker(
    symbol: str,
    db: Session,
    zones_by_depth: dict[int, dict[str, Any]],
) -> None:
    sym = symbol.strip().upper()
    row = get_stored_walker(sym, db)
    if row is None:
        row = compute_walker_for_symbol(sym, db)
    if row is None:
        return

    state = copy.deepcopy(row.walker_state_json or {})
    levels = state.get("levels")
    if not isinstance(levels, list):
        levels = []
        state["levels"] = levels

    by_depth_index: dict[int, dict[str, Any]] = {}
    for level in levels:
        if not isinstance(level, dict):
            continue
        depth_val = level.get("depth")
        if isinstance(depth_val, int):
            by_depth_index[depth_val] = level

    for depth, zone in sorted(zones_by_depth.items()):
        level = by_depth_index.get(depth)
        if level is None:
            level = {
                "depth": int(depth),
                "choch_zone": zone,
                "crossing_attempt": None,
                "choch_mitigated": False,
                "termination_reason": "manual_override_depth",
            }
            levels.append(level)
            by_depth_index[depth] = level
        else:
            level["choch_zone"] = zone

    row.walker_state_json = _json_safe(state)
    row.max_depth_reached = max(
        int(row.max_depth_reached or 0),
        max(zones_by_depth.keys()) if zones_by_depth else 0,
    )
    row.total_mitigation_count = sum(
        1
        for level in levels
        if isinstance(level, dict) and level.get("choch_mitigated") is True
    )
    row.computed_at = _now_utc()

    db.commit()


def _upsert_candidate_from_resolver(
    symbol: str,
    db: Session,
    result: dict,
    source_timeframe: str,
    choch_source: str,
    candles: list,
) -> None:
    sym = symbol.strip().upper()
    trend_result = result["trend_result"]
    legs = trend_result.get("legs") or []
    levels = compute_all_structure_levels(candles, legs, trend_result.get("trend", "range"))
    first_leg = legs[0] if legs else {}
    prime_leg = _largest_confirmed_impulse(legs)

    start_ts = first_leg.get("start_timestamp") if isinstance(first_leg, dict) else None
    if isinstance(start_ts, datetime):
        start_ts = _as_utc(start_ts)
    else:
        start_ts = _now_utc()

    start_price = float(first_leg.get("start_price") or 0.0) if isinstance(first_leg, dict) else 0.0

    row = db.query(CandidateImpulseCache).filter(CandidateImpulseCache.symbol == sym).one_or_none()
    payload = {
        "source_timeframe": source_timeframe,
        "start_price": start_price,
        "start_timestamp": start_ts,
        "choch_source": choch_source,
        "legs_json": _json_safe(legs),
        "bos_levels_json": _json_safe(levels.get("bos_levels") or []),
        "choch_zone_json": _json_safe(result.get("choch_zone")) if result.get("choch_zone") is not None else None,
        "prime_impulse_json": _json_safe(prime_leg) if prime_leg is not None else None,
        "prime_choch_zone_json": None,
        "structure_broken": None,
        "candidate_walker_json": _json_safe(row.candidate_walker_json) if row is not None and row.candidate_walker_json is not None else None,
        "computed_at": _now_utc(),
    }

    if row is None:
        row = CandidateImpulseCache(symbol=sym, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)

    db.commit()


def recompute_full_chain_for_symbol(
    symbol: str,
    db: Session,
    layers: list[str] | None = None,
) -> dict:
    sym = symbol.strip().upper()
    explicit_layers = _normalize_explicit_layers(layers)

    by_type, depth_rows, active_override_labels = _load_active_overrides(sym, db)
    if explicit_layers is None:
        layers_to_run = _layers_from_cascade(by_type, depth_rows)
    else:
        layers_to_run = explicit_layers

    layers_run: list[str] = []
    overrides_applied: list[str] = []

    for layer in _LAYER_ORDER:
        if layer not in layers_to_run:
            continue

        if layer == "global":
            trend_bounds_override = by_type.get("trend_bounds")
            global_override = by_type.get("global_choch")
            if global_override is not None or trend_bounds_override is not None:
                # Scanner global compute has no external-anchor inputs; direct cache write
                # with resolver output is the safest non-invasive injection path.
                base_row = get_stored_global_structure(sym, db)
                if base_row is None:
                    base_row = compute_global_structure_for_symbol(sym, db)

                ref_tf = _reference_tf_to_cache_tf(getattr(base_row, "reference_timeframe", "daily"))
                candles = candle_store.get_candles(sym, ref_tf, db)
                trend_direction = getattr(base_row, "trend_direction", "down")
                if trend_direction not in {"up", "down"}:
                    trend_direction = "down"

                if global_override is not None and trend_bounds_override is not None:
                    global_override.trend_bounds = trend_bounds_override
                effective_override = global_override if global_override is not None else trend_bounds_override

                resolved = resolve_global_override(effective_override, candles, trend_direction)
                if resolved is not None:
                    _upsert_global_from_resolver(sym, db, resolved, base_row.reference_timeframe, candles)
                    if global_override is not None:
                        overrides_applied.append("global_choch")
                    if trend_bounds_override is not None:
                        overrides_applied.append("trend_bounds")
                else:
                    compute_global_structure_for_symbol(sym, db)
            else:
                compute_global_structure_for_symbol(sym, db)
            layers_run.append("global")
            continue

        if layer == "prime":
            ichoch_override = by_type.get("ichoch")
            if ichoch_override is not None:
                gsc = get_stored_global_structure(sym, db)
                if gsc is None:
                    gsc = compute_global_structure_for_symbol(sym, db)
                if gsc is not None:
                    impulse = _last_confirmed_impulse(gsc.legs_json)
                    if impulse is not None:
                        start_ts = _as_utc(impulse.get("start_timestamp"))
                        end_ts = _as_utc(impulse.get("end_timestamp"))
                        if start_ts is not None and end_ts is not None:
                            tf = _reference_tf_to_cache_tf(gsc.reference_timeframe)
                            candles = candle_store.get_candles(sym, tf, db)
                            trend_direction = gsc.trend_direction if gsc.trend_direction in {"up", "down"} else "down"
                            resolved = resolve_prime_override(
                                ichoch_override,
                                candles,
                                trend_direction,
                                start_ts,
                                end_ts,
                            )
                            if resolved is not None:
                                _upsert_prime_from_resolver(
                                    sym,
                                    db,
                                    resolved,
                                    tf,
                                    start_ts,
                                    end_ts,
                                    float(impulse.get("start_price") or 0.0),
                                    float(impulse.get("end_price") or 0.0),
                                    candles,
                                )
                                overrides_applied.append("ichoch")
                            else:
                                compute_prime_impulse_structure(sym, db)
                        else:
                            compute_prime_impulse_structure(sym, db)
                    else:
                        compute_prime_impulse_structure(sym, db)
                else:
                    compute_prime_impulse_structure(sym, db)
            else:
                compute_prime_impulse_structure(sym, db)
            layers_run.append("prime")
            continue

        if layer == "walker":
            if depth_rows:
                row = get_stored_walker(sym, db)
                if row is None:
                    row = compute_walker_for_symbol(sym, db)
                if row is not None:
                    tf = row.source_timeframe
                    candles = candle_store.get_candles(sym, tf, db)
                    gsc = get_stored_global_structure(sym, db)
                    trend_direction = gsc.trend_direction if gsc and gsc.trend_direction in {"up", "down"} else "down"

                    zones: dict[int, dict[str, Any]] = {}
                    for (ot, d_idx), ov in depth_rows.items():
                        if ot != "depth_choch":
                            continue
                        zone = resolve_walker_depth_override(ov, candles, d_idx, trend_direction)
                        if zone is not None:
                            zones[int(d_idx)] = zone
                            overrides_applied.append(f"depth_choch:{int(d_idx)}")

                    if zones:
                        _apply_depth_override_zones_to_walker(sym, db, zones)
                    else:
                        compute_walker_for_symbol(sym, db)
                else:
                    compute_walker_for_symbol(sym, db)
            else:
                compute_walker_for_symbol(sym, db)
            layers_run.append("walker")
            continue

        if layer == "candidate":
            candidate_override = by_type.get("candidate_choch") or by_type.get("candidate_ichoch")
            if candidate_override is not None:
                gsc = get_stored_global_structure(sym, db)
                if gsc is None:
                    gsc = compute_global_structure_for_symbol(sym, db)
                ref_tf = _reference_tf_to_cache_tf(gsc.reference_timeframe) if gsc is not None else "1d"
                existing_candidate = db.query(CandidateImpulseCache).filter(CandidateImpulseCache.symbol == sym).one_or_none()
                source_tf = existing_candidate.source_timeframe if existing_candidate is not None else ref_tf
                candles = candle_store.get_candles(sym, source_tf, db)
                trend_direction = gsc.trend_direction if gsc and gsc.trend_direction in {"up", "down"} else "down"

                resolved = resolve_candidate_override(candidate_override, candles, trend_direction)
                if resolved is not None:
                    applied_type = "candidate_choch" if by_type.get("candidate_choch") is not None else "candidate_ichoch"
                    _upsert_candidate_from_resolver(sym, db, resolved, source_tf, applied_type, candles)
                    overrides_applied.append(applied_type)
                else:
                    compute_candidate_impulse_for_symbol(sym, db)
            else:
                compute_candidate_impulse_for_symbol(sym, db)
            layers_run.append("candidate")

    from src.api.routers.analysis import on_structure_updated

    on_structure_updated(sym, db)

    return {
        "symbol": sym,
        "layers_run": layers_run,
        "overrides_applied": sorted(set(overrides_applied)),
        "status": "complete",
        "active_overrides_loaded": sorted(set(active_override_labels)),
    }


def _recompute_bg_entry(symbol: str, layers: list[str] | None) -> None:
    db = SessionLocal()
    try:
        recompute_full_chain_for_symbol(symbol, db, layers=layers)
    except Exception:
        logger.exception("Async recompute failed for symbol=%s", symbol)
    finally:
        db.close()


def trigger_recompute_async(
    symbol: str,
    layers: list[str] | None = None,
) -> None:
    thread = threading.Thread(
        target=_recompute_bg_entry,
        args=(symbol, layers),
        daemon=True,
    )
    thread.start()
