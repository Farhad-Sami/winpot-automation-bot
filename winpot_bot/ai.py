"""Shared OpenRouter chat and JSON extraction helpers."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def extract_json(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a model response (handles optional markdown fences)."""
    cleaned = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace:
            cleaned = brace.group(0)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Model response must be a JSON object.")
    return data


async def openrouter_chat(
    model: str,
    messages: list[dict[str, Any]],
    api_key: str,
    timeout: float = 30.0,
) -> str:
    """Call OpenRouter chat completions with the user's API key and configured reasoning effort."""
    cleaned_key = api_key.strip()
    if not cleaned_key:
        raise RuntimeError("OpenRouter API key is not set. Set it in /settings or /openrouter_key <key>.")

    payload: dict[str, Any] = {"model": model, "messages": messages}
    effort = os.getenv("AI_REASONING_EFFORT", "off").strip().lower()
    if "qwen3.7" in model.lower():
        if effort in {"off", "none"}:
            payload["reasoning"] = {"effort": "none"}
        elif effort in {"low", "medium", "high"}:
            payload["reasoning"] = {"effort": effort}

    headers = {
        "Authorization": f"Bearer {cleaned_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        if resp.is_error:
            raise RuntimeError(f"OpenRouter {resp.status_code} ({model}): {resp.text[:250]}")
        return str(resp.json()["choices"][0]["message"]["content"]).strip()


async def openrouter_decisions(
    model: str,
    state: dict[str, Any],
    questions: dict[str, Any],
    api_key: str,
    timeout: float = 35.0,
) -> dict[str, Any]:
    """Call OpenRouter's Decisions API (/api/alpha/decisions) for typesafe/jev-1.14."""
    cleaned_key = api_key.strip()
    if not cleaned_key:
        raise RuntimeError("OpenRouter API key is not set. Set it in /settings or /openrouter_key <key>.")

    payload = {"model": model, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {cleaned_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(OPENROUTER_DECISIONS_URL, json=payload, headers=headers)
        if resp.is_error:
            raise RuntimeError(f"OpenRouter Decisions {resp.status_code} ({model}): {resp.text[:250]}")
        return resp.json()
