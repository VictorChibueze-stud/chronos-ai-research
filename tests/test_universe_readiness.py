"""Unit tests for universe readiness classification (cache + bootstrap failure)."""

from __future__ import annotations

import pytest

from src.api.universe_readiness_core import CANONICAL_TIMEFRAMES, classify_from_coverage


@pytest.mark.parametrize(
    ("available", "failed", "symbol", "expected_state"),
    [
        (set(CANONICAL_TIMEFRAMES), set(), "BTCUSDT", "FULL"),
        ({"1h"}, set(), "ETHUSDT", "PARTIAL"),
        (set(), set(), "XRPUSDT", "UNSCANNED"),
        (set(), {"XRPUSDT"}, "XRPUSDT", "ERROR"),
    ],
)
def test_classify_from_coverage(
    available: set[str],
    failed: set[str],
    symbol: str,
    expected_state: str,
) -> None:
    state, coverage = classify_from_coverage(available, failed, symbol)
    assert state == expected_state
    assert "available" in coverage
    assert "missing" in coverage
    if expected_state == "FULL":
        assert len(coverage["missing"]) == 0
    if expected_state == "UNSCANNED":
        assert len(coverage["available"]) == 0
