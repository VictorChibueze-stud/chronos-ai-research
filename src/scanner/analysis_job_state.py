"""Thread-safe flags for long-running analysis jobs (surfaced via /api/scanner/ranking-status)."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_state: dict[str, bool] = {
    "global_structure_in_progress": False,
    "prime_impulse_in_progress": False,
    "walker_in_progress": False,
}


def set_global_structure_running(value: bool) -> None:
    with _lock:
        _state["global_structure_in_progress"] = value


def set_prime_impulse_running(value: bool) -> None:
    with _lock:
        _state["prime_impulse_in_progress"] = value


def set_walker_running(value: bool) -> None:
    with _lock:
        _state["walker_in_progress"] = value


def get_analysis_job_flags() -> dict[str, Any]:
    with _lock:
        return dict(_state)
