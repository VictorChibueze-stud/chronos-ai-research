"""Pure readiness classification (no DB imports)."""

from __future__ import annotations

# Must stay aligned with frontend/src/app/market/page.tsx TIMEFRAMES
CANONICAL_TIMEFRAMES: tuple[str, ...] = (
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
    "1w",
    "1mo",
)

MIN_BARS = 5


def _normalize_tf(tf: str) -> str:
    return (tf or "").strip().lower()


def classify_from_coverage(
    available_tfs: set[str],
    bootstrap_failed_symbols: set[str],
    symbol: str,
) -> tuple[str, dict[str, list[str]]]:
    """Return (readiness_state, readiness_coverage) for one symbol (symbol upper-case)."""
    sym = symbol.upper()
    canonical = {_normalize_tf(x) for x in CANONICAL_TIMEFRAMES}
    have = {_normalize_tf(x) for x in available_tfs} & canonical
    tf_order = {t: i for i, t in enumerate(CANONICAL_TIMEFRAMES)}
    missing = sorted(canonical - have, key=lambda t: tf_order.get(t, 99))
    available_sorted = sorted(have, key=lambda t: tf_order.get(t, 99))

    if len(have) == len(canonical):
        state = "FULL"
    elif len(have) > 0:
        state = "PARTIAL"
    elif sym in bootstrap_failed_symbols:
        state = "ERROR"
    else:
        state = "UNSCANNED"

    coverage = {"available": available_sorted, "missing": missing}
    return state, coverage
