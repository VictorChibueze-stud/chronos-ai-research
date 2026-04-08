from __future__ import annotations

from src.execution.symbol_map import resolve_deriv_symbol


def test_resolve_deriv_known_name():
    assert resolve_deriv_symbol("Volatility 10 Index") == "R_10"


def test_resolve_deriv_code_passthrough():
    assert resolve_deriv_symbol("R_25") == "R_25"


def test_filter_defaults_keys():
    from src.core.filter_defaults import SCAN_AND_ANALYSIS_FILTER_DEFAULTS

    assert "use_momentum_filter" in SCAN_AND_ANALYSIS_FILTER_DEFAULTS
    assert SCAN_AND_ANALYSIS_FILTER_DEFAULTS["min_dominance_ratio"] == 1.5
