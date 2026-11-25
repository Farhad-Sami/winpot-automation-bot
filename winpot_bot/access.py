"""Access token verification against ACCESS_URL."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class AccessStatus:
    """Result of checking a user's access token."""

    allowed: bool
    reason: str
    ends_at: int | None = None


def parse_access_response(data: dict[str, Any], now: float | None = None) -> AccessStatus:
    """Validate an access-check JSON payload like {'token': '...', 'status': 'active', 'limit': {'ends': ...}}."""
    status = str(data.get("status", "")).strip().lower()
    limit = data.get("limit") or {}
    ends_raw = limit.get("ends") if isinstance(limit, dict) else None

    ends_at: int | None = None
    if ends_raw is not None:
        try:
            ends_at = int(ends_raw)
        except (TypeError, ValueError):
            return AccessStatus(allowed=False, reason="Invalid expiration timestamp from access server.")

    if status != "active":
        return AccessStatus(
            allowed=False,
            reason=f"Access is not active (status: {status or 'unknown'}).",
            ends_at=ends_at,
        )

    current_ts = time.time() if now is None else now
    if ends_at is not None and current_ts >= ends_at:
        return AccessStatus(
            allowed=False,
            reason="Your access token has expired.",
            ends_at=ends_at,
        )

    return AccessStatus(allowed=True, reason="Active", ends_at=ends_at)


async def verify_access_token(token: str) -> AccessStatus:
    """Check `token` against ACCESS_URL?token={token}."""
    cleaned = token.strip()
    if not cleaned:
        return AccessStatus(allowed=False, reason="No access token provided.")

    access_url = os.getenv("ACCESS_URL", "").strip()
    if not access_url:
        return AccessStatus(allowed=False, reason="Access server is not configured.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(access_url, params={"token": cleaned})
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return AccessStatus(allowed=False, reason="Unexpected access server response.")
            return parse_access_response(data)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403, 404}:
            return AccessStatus(allowed=False, reason="Invalid or unauthorized access token.")
        return AccessStatus(allowed=False, reason="Access verification failed. Try again later.")
    except Exception:
        return AccessStatus(allowed=False, reason="Could not reach access verification server.")
