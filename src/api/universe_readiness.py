"""Universe candle-cache readiness: FULL / PARTIAL / ERROR / UNSCANNED."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.universe_readiness_core import (
    CANONICAL_TIMEFRAMES,
    MIN_BARS,
    classify_from_coverage,
)
from src.db.models import CandleCache, UniverseBootstrapFailure

__all__ = [
    "CANONICAL_TIMEFRAMES",
    "MIN_BARS",
    "build_readiness_index",
    "classify_from_coverage",
    "merge_readiness_fields",
]


def load_bootstrap_failure_symbols(db: Session) -> set[str]:
    rows = db.query(UniverseBootstrapFailure.symbol).all()
    return {str(r[0]).upper() for r in rows}


def load_candle_counts_by_symbol_timeframe(
    db: Session,
    symbols_upper: Iterable[str],
) -> dict[str, dict[str, int]]:
    """Return symbol_upper -> {timeframe_lower -> count} for rows in candle_cache."""
    sym_list = [s.upper() for s in symbols_upper]
    if not sym_list:
        return {}

    chunk_size = 400
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for i in range(0, len(sym_list), chunk_size):
        chunk = sym_list[i : i + chunk_size]
        rows = (
            db.query(
                func.upper(CandleCache.symbol).label("sym"),
                func.lower(CandleCache.timeframe).label("tf"),
                func.count(CandleCache.id).label("cnt"),
            )
            .filter(func.upper(CandleCache.symbol).in_(chunk))
            .group_by(func.upper(CandleCache.symbol), func.lower(CandleCache.timeframe))
            .all()
        )
        for sym, tf, cnt in rows:
            su = str(sym).upper()
            tl = (str(tf) or "").strip().lower()
            counts[su][tl] = int(cnt or 0)

    return {k: dict(v) for k, v in counts.items()}


def build_readiness_index(
    db: Session,
    symbols_upper: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """For each symbol, compute readiness_state and readiness_coverage."""
    sym_set = {s.upper() for s in symbols_upper}
    failed = load_bootstrap_failure_symbols(db)
    raw_counts = load_candle_counts_by_symbol_timeframe(db, sym_set)

    index: dict[str, dict[str, Any]] = {}
    for sym in sym_set:
        per_tf = raw_counts.get(sym, {})
        available = {tf for tf, c in per_tf.items() if c >= MIN_BARS}
        state, coverage = classify_from_coverage(available, failed, sym)
        index[sym] = {
            "readiness_state": state,
            "readiness_coverage": coverage,
        }
    return index


def merge_readiness_fields(target: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    if readiness:
        target["readiness_state"] = readiness.get("readiness_state", "UNSCANNED")
        target["readiness_coverage"] = readiness.get(
            "readiness_coverage",
            {"available": [], "missing": list(CANONICAL_TIMEFRAMES)},
        )
    else:
        target.setdefault("readiness_state", "UNSCANNED")
        target.setdefault(
            "readiness_coverage",
            {"available": [], "missing": list(CANONICAL_TIMEFRAMES)},
        )
    return target
