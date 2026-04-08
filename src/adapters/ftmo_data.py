from __future__ import annotations

import os
from typing import Any, Dict

import requests


def fetch_ftmo_account_info(
    api_key: str,
    *,
    base_url: str | None = None,
    account_endpoint: str | None = None,
) -> Dict[str, Any]:
    """Fetch FTMO account details using official API host with configurable endpoint.

    The exact FTMO account endpoint can vary by account type. This function keeps
    endpoint configurable via env so deployments can adapt without code changes.
    """
    resolved_base = (base_url or os.getenv("FTMO_API_BASE_URL") or "https://api.ftmo.com").rstrip("/")
    resolved_endpoint = account_endpoint or os.getenv("FTMO_ACCOUNT_ENDPOINT") or "/v1/account"
    if not resolved_endpoint.startswith("/"):
        resolved_endpoint = "/" + resolved_endpoint

    response = requests.get(
        f"{resolved_base}{resolved_endpoint}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"FTMO account request failed: {response.status_code}")
    return response.json()
