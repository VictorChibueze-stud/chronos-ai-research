from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from src.adapters.binance_data import fetch_binance_testnet_account
from src.adapters.deriv_data import fetch_deriv_account_balance
from src.adapters.ftmo_data import fetch_ftmo_account_info


_BROKERS = ("binance", "deriv", "ftmo")
_integration_state: Dict[str, Dict[str, Any]] = {
    broker: {
        "connected": False,
        "health": "unknown",
        "last_sync": None,
        "message": "Not tested yet.",
        "account": None,
    }
    for broker in _BROKERS
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_or_payload(payload_value: str | None, env_var: str) -> str | None:
    if payload_value:
        return payload_value
    env_value = os.getenv(env_var)
    return env_value if env_value else None


def _set_broker_state(
    broker: str,
    *,
    connected: bool,
    health: str,
    message: str,
    account: Dict[str, Any] | None,
) -> Dict[str, Any]:
    _integration_state[broker] = {
        "connected": connected,
        "health": health,
        "last_sync": _now_iso(),
        "message": message,
        "account": account,
    }
    return _integration_state[broker]


def get_integrations_status() -> Dict[str, Any]:
    return {
        "status": "ok",
        "generated_at": _now_iso(),
        "brokers": [
            {
                "broker": broker,
                "connected": bool(_integration_state[broker]["connected"]),
                "health": str(_integration_state[broker]["health"]),
                "last_sync": _integration_state[broker]["last_sync"],
                "message": str(_integration_state[broker]["message"]),
                "account": _integration_state[broker]["account"],
            }
            for broker in _BROKERS
        ],
    }


def test_binance_connection(api_key: str | None, api_secret: str | None) -> Dict[str, Any]:
    effective_key = _env_or_payload(api_key, "BINANCE_TESTNET_API_KEY")
    effective_secret = _env_or_payload(api_secret, "BINANCE_TESTNET_API_SECRET")
    if not effective_key or not effective_secret:
        state = _set_broker_state(
            "binance",
            connected=False,
            health="offline",
            message="Missing Binance credentials (payload or env).",
            account=None,
        )
        return {"ok": False, "broker": "binance", "message": state["message"], "checked_at": _now_iso(), "account": None}

    try:
        raw = fetch_binance_testnet_account(effective_key, effective_secret)
        balances = raw.get("balances", [])
        non_zero = [b for b in balances if float(b.get("free", 0) or 0) > 0 or float(b.get("locked", 0) or 0) > 0]
        primary = non_zero[0] if non_zero else {"asset": "USDT", "free": 0}
        account = {
            "account_id": str(raw.get("uid") or raw.get("accountType") or "binance-testnet"),
            "balance": float(primary.get("free", 0) or 0),
            "currency": str(primary.get("asset", "USDT")),
            "raw": {"canTrade": raw.get("canTrade"), "accountType": raw.get("accountType")},
        }
        state = _set_broker_state(
            "binance",
            connected=True,
            health="healthy",
            message="Binance testnet connection successful.",
            account=account,
        )
        return {"ok": True, "broker": "binance", "message": state["message"], "checked_at": _now_iso(), "account": account}
    except Exception:
        state = _set_broker_state(
            "binance",
            connected=False,
            health="offline",
            message="Binance testnet connection failed.",
            account=None,
        )
        return {"ok": False, "broker": "binance", "message": state["message"], "checked_at": _now_iso(), "account": None}


def test_deriv_connection(token: str | None) -> Dict[str, Any]:
    effective_token = _env_or_payload(token, "DERIV_API_TOKEN")
    if not effective_token:
        state = _set_broker_state(
            "deriv",
            connected=False,
            health="offline",
            message="Missing Deriv token (payload or env).",
            account=None,
        )
        return {"ok": False, "broker": "deriv", "message": state["message"], "checked_at": _now_iso(), "account": None}

    try:
        raw = fetch_deriv_account_balance(effective_token)
        bal = raw.get("balance", {}) if isinstance(raw, dict) else {}
        account = {
            "account_id": str(bal.get("loginid") or "deriv-demo"),
            "balance": float(bal.get("balance", 0) or 0),
            "currency": str(bal.get("currency", "USD")),
            "raw": {"is_virtual": bal.get("is_virtual"), "id": bal.get("id")},
        }
        state = _set_broker_state(
            "deriv",
            connected=True,
            health="healthy",
            message="Deriv connection successful.",
            account=account,
        )
        return {"ok": True, "broker": "deriv", "message": state["message"], "checked_at": _now_iso(), "account": account}
    except Exception:
        state = _set_broker_state(
            "deriv",
            connected=False,
            health="offline",
            message="Deriv connection failed.",
            account=None,
        )
        return {"ok": False, "broker": "deriv", "message": state["message"], "checked_at": _now_iso(), "account": None}


def test_ftmo_connection(api_key: str | None) -> Dict[str, Any]:
    effective_key = _env_or_payload(api_key, "FTMO_API_KEY")
    if not effective_key:
        state = _set_broker_state(
            "ftmo",
            connected=False,
            health="offline",
            message="Missing FTMO API key (payload or env).",
            account=None,
        )
        return {"ok": False, "broker": "ftmo", "message": state["message"], "checked_at": _now_iso(), "account": None}

    try:
        raw = fetch_ftmo_account_info(effective_key)
        account = {
            "account_id": str(raw.get("account_id") or raw.get("id") or "ftmo-account"),
            "balance": float(raw.get("balance", 0) or 0),
            "currency": str(raw.get("currency", "USD")),
            "challenge_status": str(raw.get("challenge_status") or raw.get("status") or "unknown"),
            "raw": raw if isinstance(raw, dict) else {"value": raw},
        }
        state = _set_broker_state(
            "ftmo",
            connected=True,
            health="healthy",
            message="FTMO connection successful.",
            account=account,
        )
        return {"ok": True, "broker": "ftmo", "message": state["message"], "checked_at": _now_iso(), "account": account}
    except Exception:
        state = _set_broker_state(
            "ftmo",
            connected=False,
            health="degraded",
            message="FTMO connection failed. Verify FTMO endpoint/env configuration.",
            account=None,
        )
        return {"ok": False, "broker": "ftmo", "message": state["message"], "checked_at": _now_iso(), "account": None}
