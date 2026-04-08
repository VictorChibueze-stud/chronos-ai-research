from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import websocket

from src.execution.contracts import NormalizedOrderIntent, ProviderId
from src.execution.providers.base import ExecutionProvider, ProviderPlacementResult

logger = logging.getLogger(__name__)

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"


def _recv_until(ws: websocket.WebSocket, keys: set[str], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ws.settimeout(max(1.0, deadline - time.time()))
        raw = ws.recv()
        msg = json.loads(raw)
        if "echo_req" in msg:
            continue
        if "error" in msg and msg["error"]:
            return msg
        if keys.intersection(msg.keys()):
            return msg
    raise TimeoutError("Timed out waiting for Deriv WS response")


class DerivExecutionProvider:
    """Deriv WebSocket: authorize → proposal → buy (synthetics / options-style contracts)."""

    def __init__(self, *, app_id: str | None = None, api_token: str | None = None) -> None:
        self._app_id = (app_id or os.getenv("DERIV_APP_ID") or "1089").strip()
        self._api_token = (api_token or os.getenv("DERIV_API_TOKEN") or "").strip()

    @property
    def provider_id(self) -> ProviderId:
        return ProviderId.DERIV

    def place_order(self, intent: NormalizedOrderIntent, resolved_symbol: str) -> ProviderPlacementResult:
        diagnostics: list[dict[str, Any]] = []
        if not self._api_token:
            return ProviderPlacementResult(
                success=False,
                error_code="missing_token",
                error_message="DERIV_API_TOKEN is not set",
                diagnostics=diagnostics,
            )

        contract_type = intent.contract_type or ("CALL" if intent.side == "long" else "PUT")
        url = DERIV_WS_URL.format(app_id=self._app_id)
        ws: websocket.WebSocket | None = None
        try:
            ws = websocket.create_connection(url, timeout=30)
            ws.send(json.dumps({"authorize": self._api_token}))
            auth_msg = _recv_until(ws, {"authorize", "error"})
            diagnostics.append({"stage": "authorize", "keys": list(auth_msg.keys())})
            if "error" in auth_msg:
                err = auth_msg.get("error") or {}
                return ProviderPlacementResult(
                    success=False,
                    error_code=str(err.get("code") or "authorize_failed"),
                    error_message=str(err.get("message") or err),
                    diagnostics=diagnostics,
                )

            req_id = 1
            proposal_req = {
                "req_id": req_id,
                "proposal": 1,
                "amount": float(intent.stake_amount),
                "basis": intent.basis,
                "contract_type": contract_type,
                "currency": intent.currency,
                "duration": int(intent.duration),
                "duration_unit": intent.duration_unit,
                "symbol": resolved_symbol,
            }
            ws.send(json.dumps(proposal_req))
            prop_msg = _recv_until(ws, {"proposal", "error"})
            diagnostics.append({"stage": "proposal_response", "keys": list(prop_msg.keys())})
            if "error" in prop_msg and prop_msg["error"]:
                err = prop_msg.get("error") or {}
                return ProviderPlacementResult(
                    success=False,
                    error_code=str(err.get("code") or "proposal_failed"),
                    error_message=str(err.get("message") or err),
                    diagnostics=diagnostics,
                )

            prop = prop_msg.get("proposal") or {}
            proposal_id = prop.get("id")
            ask_price = prop.get("ask_price")
            if not proposal_id:
                return ProviderPlacementResult(
                    success=False,
                    error_code="missing_proposal_id",
                    error_message="Deriv proposal response had no id",
                    diagnostics=diagnostics,
                )

            price = float(ask_price) if ask_price is not None else float(intent.stake_amount)
            buy_req = {
                "req_id": req_id + 1,
                "buy": str(proposal_id),
                "price": price,
            }
            ws.send(json.dumps(buy_req))
            buy_msg = _recv_until(ws, {"buy", "error"})
            diagnostics.append({"stage": "buy_response", "keys": list(buy_msg.keys())})
            if "error" in buy_msg and buy_msg["error"]:
                err = buy_msg.get("error") or {}
                return ProviderPlacementResult(
                    success=False,
                    error_code=str(err.get("code") or "buy_failed"),
                    error_message=str(err.get("message") or err),
                    diagnostics=diagnostics,
                )

            buy_payload = buy_msg.get("buy") or {}
            contract_id = buy_payload.get("contract_id") or buy_payload.get("transaction_id")
            return ProviderPlacementResult(
                success=True,
                provider_order_id=str(contract_id) if contract_id else str(proposal_id),
                diagnostics=diagnostics,
            )
        except Exception as exc:
            logger.warning("Deriv placement failed: %s", exc)
            return ProviderPlacementResult(
                success=False,
                error_code="exception",
                error_message=str(exc),
                diagnostics=diagnostics,
            )
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
