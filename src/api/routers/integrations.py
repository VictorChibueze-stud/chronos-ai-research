from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.services.integrations_service import (
    get_integrations_status,
    test_binance_connection,
    test_deriv_connection,
    test_ftmo_connection,
)


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class IntegrationTestPayload(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    token: str | None = None


@router.get("/status")
def integrations_status() -> dict[str, Any]:
    return get_integrations_status()


@router.post("/binance/test")
def integrations_binance_test(payload: IntegrationTestPayload) -> dict[str, Any]:
    return test_binance_connection(payload.api_key, payload.api_secret)


@router.post("/deriv/test")
def integrations_deriv_test(payload: IntegrationTestPayload) -> dict[str, Any]:
    return test_deriv_connection(payload.token or payload.api_key)


@router.post("/ftmo/test")
def integrations_ftmo_test(payload: IntegrationTestPayload) -> dict[str, Any]:
    return test_ftmo_connection(payload.api_key)
