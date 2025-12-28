"""
fourover_client.py
------------------
Minimal, crash-proof 4over client.

GOALS:
- Never crash the FastAPI app at import time
- Centralize all 4over HTTP calls here
- Make auth debugging explicit and visible
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


# ========== CONFIG ==========
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY")


def _assert_env() -> None:
    """Fail fast but cleanly if env vars are missing."""
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is not set")
    if not FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is not set")


# ========== PUBLIC API ==========
async def call_4over(
    path: str,
    *,
    method: str = "GET",
    query: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Generic 4over API caller.

    NOTE:
    - This currently sends ONLY the apikey (no signature yet)
    - Expected to return 401 until auth is finalized
    - Designed so the app never crashes
    """

    _assert_env()

    method = method.upper()
    path = "/" + path.lstrip("/")

    params: Dict[str, Any] = {"apikey": FOUR_OVER_APIKEY}
    if query:
        params.update(query)

    url = f"{FOUR_OVER_BASE_URL}{path}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method=method,
            url=url,
            params=params,
            json=json,
            headers={"Accept": "application/json"},
        )

        content_type = resp.headers.get("content-type", "").lower()

        try:
            data = resp.json() if "application/json" in content_type else {"raw": resp.text}
        except Exception:
            data = {"raw": resp.text}

        return {
            "http_status": resp.status_code,
            "ok": 200 <= resp.status_code < 300,
            "data": data,
            "debug": {
                "url": url,
                "method": method,
                "query": params,
            },
        }
