from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Any

import yaml

_SYMBOLS_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "config" / "symbols.yaml"


@lru_cache(maxsize=1)
def _deriv_name_to_code() -> dict[str, str]:
    try:
        with _SYMBOLS_PATH.open(encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
    except OSError:
        return {}
    deriv = data.get("deriv") or {}
    out: dict[str, str] = {}
    for name, code in deriv.items():
        out[str(name).strip().lower()] = str(code).strip()
    return out


@lru_cache(maxsize=1)
def _deriv_code_set() -> frozenset[str]:
    return frozenset(_deriv_name_to_code().values())


def resolve_deriv_symbol(symbol: str) -> str:
    """Map display name or Chronos code to Deriv contract symbol (e.g. R_10)."""
    s = symbol.strip()
    if not s:
        return s
    upper = s.upper()
    if upper in _deriv_code_set():
        return upper
    mapped = _deriv_name_to_code().get(s.lower())
    if mapped:
        return mapped.upper()
    return upper
