"""Shared default kwargs for identify_trend / compute_internal_structure / scanner.

Keep Market View (GET /api/analysis), setups scan, and universe scanner aligned.
"""
from __future__ import annotations

from typing import Any

# Mirrors prior analysis.FILTER_CONFIG — single source of truth.
SCAN_AND_ANALYSIS_FILTER_DEFAULTS: dict[str, Any] = {
    "use_parent_relative_filter": True,
    "min_impulse_parent_ratio": 0.15,
    "use_momentum_filter": True,
    "min_momentum_ratio": 0.5,
    "use_dominance_filter": True,
    "min_dominance_ratio": 1.5,
}
