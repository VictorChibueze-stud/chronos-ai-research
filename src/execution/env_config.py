from __future__ import annotations

import os


def execution_enabled() -> bool:
    return os.getenv("EXECUTION_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def execution_paper_only() -> bool:
    v = os.getenv("EXECUTION_PAPER_ONLY", "true").strip().lower()
    return v in {"1", "true", "yes", "on"}


def execution_provider() -> str:
    return os.getenv("EXECUTION_PROVIDER", "deriv").strip().lower() or "deriv"
