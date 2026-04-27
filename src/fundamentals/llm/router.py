"""
LLM waterfall router for fundamentals analysis.

Maintains a daily request counter per model
in memory. When a model hits its daily quota,
automatically rotates to the next model in
the priority list.

All models are called via the OpenRouter API
using the OpenAI-compatible format.
Single API key required: OPENROUTER_API_KEY.

Priority order (highest reasoning to lowest):
1. meta-llama/llama-3.3-70b-instruct:free
2. google/gemma-3-27b-it:free
3. nvidia/nemotron-3-super-120b-a12b:free
4. mistralai/mistral-small-3.1-24b-instruct:free
5. deepseek/deepseek-r1:free
6. google/gemma-3-12b-it:free

Daily quota per model: 200 requests.
Total daily capacity: 1200 requests (6 x 200).
Required for 50 markets x 3 calls: 150/day.
"""
from __future__ import annotations

import json
import logging
import os
import time as _time
import threading as _threading
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Model priority list — highest capability first.
_MODEL_WATERFALL = [
    # Tier 1 — strongest reasoning, highest quota priority
    "meta-llama/llama-3.3-70b-instruct:free",
    # Tier 2 — Google Gemma 27B, reliable fallback
    "google/gemma-3-27b-it:free",
    # Tier 3 — NVIDIA Nemotron, 120B MoE, strong
    "nvidia/nemotron-3-super-120b-a12b:free",
    # Tier 4 — Mistral Small 3.1 (replaces deprecated 7B)
    "mistralai/mistral-small-3.1-24b-instruct:free",
    # Tier 5 — DeepSeek R1, strong reasoning
    "deepseek/deepseek-r1:free",
    # Tier 6 — Gemma 12B, lighter but reliable
    "google/gemma-3-12b-it:free",
]

# Daily quota per free model on OpenRouter.
_DAILY_QUOTA_PER_MODEL = 200

# In-memory quota tracker keyed by model id.
# Shape: {model_id: {"date": "2026-04-22", "count": 47}}
_quota: dict[str, dict[str, Any]] = {}
_quota_lock = _threading.Lock()

# Minimum seconds between consecutive LLM calls
# to respect the 20 req/min RPM limit.
# 3.5 seconds = max 17 req/min — safe buffer.
_LAST_CALL_TIME: float = 0.0
_MIN_CALL_INTERVAL: float = 3.5
_call_time_lock = _threading.Lock()


def _throttle_rpm() -> None:
    """Block until safe to make the next call.
    Ensures no more than ~17 calls per minute
    across all models combined."""
    global _LAST_CALL_TIME
    with _call_time_lock:
        now = _time.monotonic()
        elapsed = now - _LAST_CALL_TIME
        if elapsed < _MIN_CALL_INTERVAL:
            _time.sleep(
                _MIN_CALL_INTERVAL - elapsed
            )
        _LAST_CALL_TIME = _time.monotonic()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_remaining_quota(model_id: str) -> int:
    """Return how many calls this model has left today."""
    today = _today_utc()
    with _quota_lock:
        entry = _quota.get(model_id)
        if entry is None or entry["date"] != today:
            return _DAILY_QUOTA_PER_MODEL
        return max(
            0,
            _DAILY_QUOTA_PER_MODEL - entry["count"],
        )


def _increment_quota(model_id: str) -> None:
    today = _today_utc()
    with _quota_lock:
        entry = _quota.get(model_id)
        if entry is None or entry["date"] != today:
            _quota[model_id] = {"date": today, "count": 1}
        else:
            entry["count"] += 1


def get_quota_status() -> dict[str, int]:
    """Return remaining quota per model.

    Used by the /api/system/health endpoint.
    """
    return {m: _get_remaining_quota(m) for m in _MODEL_WATERFALL}


def call_llm_with_fallback(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    call_type: str = "general",
) -> dict[str, Any] | None:
    """
    Call the LLM waterfall with automatic model rotation
    on quota exhaustion.

    Returns parsed JSON dict on success. Returns None when
    all models are exhausted — callers must handle None
    gracefully and default to ALLOW for trading.

    ``call_type`` is for logging only:
    "filter" | "cluster" | "veto" | "general".
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.warning(
            "OPENROUTER_API_KEY not set — LLM calls disabled"
        )
        return None

    for model_id in _MODEL_WATERFALL:
        remaining = _get_remaining_quota(model_id)
        if remaining <= 0:
            logger.debug(
                "Model %s quota exhausted, trying next",
                model_id,
            )
            continue

        try:
            # Respect RPM limit before every call
            _throttle_rpm()

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://ikenga.ai",
                    "X-Title": "IKENGA Trading",
                },
                json={
                    "model": model_id,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )

            if response.status_code == 429:
                # 429 can mean RPM limit (clears in seconds)
                # or daily quota (no point retrying today).
                # Retry once after a short wait before
                # deciding this model is exhausted.
                logger.warning(
                    "Model %s rate limited (429), "
                    "waiting 6s before retry",
                    model_id,
                )
                _time.sleep(6)
                try:
                    retry_response = requests.post(
                        "https://openrouter.ai/api/v1"
                        "/chat/completions",
                        headers={
                            "Authorization":
                                f"Bearer {api_key}",
                            "Content-Type":
                                "application/json",
                            "HTTP-Referer":
                                "https://ikenga.ai",
                            "X-Title": "IKENGA Trading",
                        },
                        json={
                            "model": model_id,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": system_prompt,
                                },
                                {
                                    "role": "user",
                                    "content": user_prompt,
                                },
                            ],
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "response_format": {
                                "type": "json_object"
                            },
                        },
                        timeout=60,
                    )
                    if retry_response.status_code == 429:
                        # Still 429 after retry — this model
                        # is genuinely exhausted for now.
                        # Mark it and move to next model.
                        logger.warning(
                            "Model %s still 429 after "
                            "retry — marking exhausted",
                            model_id,
                        )
                        with _quota_lock:
                            _quota[model_id] = {
                                "date": _today_utc(),
                                "count": _DAILY_QUOTA_PER_MODEL,
                            }
                        continue
                    elif retry_response.status_code == 200:
                        # Retry succeeded — process normally
                        # (fall through to JSON parsing below)
                        response = retry_response
                        # Do NOT continue — fall through
                    else:
                        logger.warning(
                            "Model %s retry returned %d, "
                            "trying next model",
                            model_id,
                            retry_response.status_code,
                        )
                        continue
                except Exception as retry_err:
                    logger.warning(
                        "Model %s retry failed: %s",
                        model_id,
                        retry_err,
                    )
                    continue

            if response.status_code != 200:
                logger.warning(
                    "Model %s returned %d, trying next",
                    model_id,
                    response.status_code,
                )
                continue

            # 200 reached — parse and validate
            data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if not content:
                logger.warning(
                    "Model %s returned empty content",
                    model_id,
                )
                continue

            clean = content.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(
                    lines[1:-1]
                    if lines[-1].strip() == "```"
                    else lines[1:]
                )

            result = json.loads(clean)

            # Only increment quota after confirmed success
            _increment_quota(model_id)
            logger.info(
                "LLM call [%s] succeeded via %s",
                call_type,
                model_id,
            )
            return result

        except json.JSONDecodeError as e:
            logger.warning(
                "Model %s returned invalid JSON: %s",
                model_id,
                e,
            )
            continue
        except requests.RequestException as e:
            logger.warning(
                "Model %s request failed: %s",
                model_id,
                e,
            )
            continue
        except Exception as e:  # noqa: BLE001 — defensive catch-all
            logger.warning(
                "Model %s unexpected error: %s",
                model_id,
                e,
            )
            continue

    logger.warning(
        "All LLM models exhausted for call_type=%s — "
        "defaulting to None",
        call_type,
    )
    return None
