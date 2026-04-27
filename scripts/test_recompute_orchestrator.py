from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import and_, or_, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.recompute_orchestrator import recompute_full_chain_for_symbol  # noqa: E402
from src.cache import candle_store  # noqa: E402
from src.db.models import (  # noqa: E402
    AnalysisResultCache,
    CandidateImpulseCache,
    GlobalStructureCache,
    ManualStructureOverride,
    MonitoredSetup,
    PrimeImpulseStructure,
    StoredWalkerResult,
)
from src.db.session import SessionLocal  # noqa: E402


def _print_result(name: str, passed: bool) -> bool:
    print(f"{name}: {'PASS' if passed else 'FAIL'}")
    return passed


def _choose_symbol(db) -> str:
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(MonitoredSetup.symbol)
        .join(GlobalStructureCache, GlobalStructureCache.symbol == MonitoredSetup.symbol)
        .join(PrimeImpulseStructure, PrimeImpulseStructure.symbol == MonitoredSetup.symbol)
        .join(StoredWalkerResult, StoredWalkerResult.symbol == MonitoredSetup.symbol)
        .join(CandidateImpulseCache, CandidateImpulseCache.symbol == MonitoredSetup.symbol)
        .distinct()
        .all()
    )

    for (symbol,) in candidates:
        active = (
            db.query(ManualStructureOverride.id)
            .filter(
                ManualStructureOverride.symbol == symbol,
                ManualStructureOverride.is_active.is_(True),
                or_(
                    ManualStructureOverride.expires_at.is_(None),
                    ManualStructureOverride.expires_at > now,
                ),
            )
            .first()
        )
        if active is None:
            return str(symbol).upper()

    raise RuntimeError("No monitored symbol found with full cache data and no active overrides")


def _table_timestamps(db, symbol: str) -> dict[str, datetime | None]:
    g = db.query(GlobalStructureCache).filter(GlobalStructureCache.symbol == symbol).one_or_none()
    p = db.query(PrimeImpulseStructure).filter(PrimeImpulseStructure.symbol == symbol).one_or_none()
    w = db.query(StoredWalkerResult).filter(StoredWalkerResult.symbol == symbol).one_or_none()
    c = db.query(CandidateImpulseCache).filter(CandidateImpulseCache.symbol == symbol).one_or_none()
    return {
        "global": g.computed_at if g else None,
        "prime": p.computed_at if p else None,
        "walker": w.computed_at if w else None,
        "candidate": c.computed_at if c else None,
    }


def _insert_dummy_analysis_cache(db, symbol: str) -> None:
    now = datetime.now(timezone.utc)
    row = db.query(AnalysisResultCache).filter(
        AnalysisResultCache.symbol == symbol,
        AnalysisResultCache.timeframe == "1h",
    ).one_or_none()
    if row is None:
        row = AnalysisResultCache(
            symbol=symbol,
            timeframe="1h",
            result_json={"dummy": True},
            params_hash="sprint4-dummy",
            computed_at=now,
            ttl_seconds=14400,
        )
        db.add(row)
    else:
        row.result_json = {"dummy": True}
        row.params_hash = "sprint4-dummy"
        row.computed_at = now
        row.ttl_seconds = 14400
    db.commit()


def test_full_recompute_no_overrides(db, symbol: str) -> bool:
    before = _table_timestamps(db, symbol)
    _insert_dummy_analysis_cache(db, symbol)

    result = recompute_full_chain_for_symbol(symbol, db, layers=None)
    after = _table_timestamps(db, symbol)

    cache_left = db.query(AnalysisResultCache).filter(AnalysisResultCache.symbol == symbol).count()

    return (
        result.get("status") == "complete"
        and set(result.get("layers_run", [])) == {"global", "prime", "walker", "candidate"}
        and all(after[layer] is not None for layer in ("global", "prime", "walker", "candidate"))
        and all(
            before[layer] is None or after[layer] >= before[layer]
            for layer in ("global", "prime", "walker", "candidate")
        )
        and cache_left == 0
    )


def test_candidate_only_layer(db, symbol: str) -> bool:
    before = _table_timestamps(db, symbol)
    result = recompute_full_chain_for_symbol(symbol, db, layers=["candidate"])
    after = _table_timestamps(db, symbol)

    unchanged = (
        after["global"] == before["global"]
        and after["prime"] == before["prime"]
        and after["walker"] == before["walker"]
    )
    candidate_updated = after["candidate"] is not None and (
        before["candidate"] is None or after["candidate"] >= before["candidate"]
    )

    return (
        result.get("status") == "complete"
        and result.get("layers_run") == ["candidate"]
        and unchanged
        and candidate_updated
    )


def test_global_override_applied(db, symbol: str) -> bool:
    gsc = db.query(GlobalStructureCache).filter(GlobalStructureCache.symbol == symbol).one_or_none()
    if gsc is None:
        return False

    tf = "1w" if (gsc.reference_timeframe or "").lower() == "weekly" else "1d"
    candles = candle_store.get_candles(symbol, tf, db)
    if len(candles) < 5:
        return False

    a_idx = max(1, len(candles) // 3)
    b_idx = min(len(candles) - 2, (len(candles) * 2) // 3)

    synthetic = ManualStructureOverride(
        symbol=symbol,
        override_type="global_choch",
        approx_price_a=float(candles[a_idx].close),
        approx_timestamp_a=candles[a_idx].timestamp,
        approx_price_b=float(candles[b_idx].close),
        approx_timestamp_b=candles[b_idx].timestamp,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    try:
        db.add(synthetic)
        db.commit()

        result = recompute_full_chain_for_symbol(symbol, db, layers=None)
        applied = set(result.get("overrides_applied", []))
        return result.get("status") == "complete" and "global_choch" in applied
    finally:
        db.rollback()
        db.query(ManualStructureOverride).filter(
            ManualStructureOverride.symbol == symbol,
            ManualStructureOverride.override_type == "global_choch",
        ).delete()
        db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        symbol = _choose_symbol(db)
        print(f"Using symbol: {symbol}")

        results = [
            _print_result("1) Full recompute no overrides", test_full_recompute_no_overrides(db, symbol)),
            _print_result("2) Candidate-only recompute", test_candidate_only_layer(db, symbol)),
            _print_result("3) Synthetic global_choch override applied", test_global_override_applied(db, symbol)),
        ]

        passed = sum(1 for r in results if r)
        print(f"\nSummary: {passed}/3 passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
