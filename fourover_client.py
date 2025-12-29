import hashlib
import hmac
import os
import requests
from typing import Dict, Any, Optional

def _clean(value: str) -> str:
    return (value or "").strip()

def fourover_signature(private_key: str, method: str) -> str:
    pk = _clean(private_key).encode("utf-8")
    key = hashlib.sha256(pk).hexdigest().encode("utf-8")
    msg = method.upper().encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

class FourOverClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        apikey: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout: int = 30,
    ):
        self.base_url = (base_url or os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")).rstrip("/")
        self.apikey = _clean(apikey or os.getenv("FOUR_OVER_APIKEY"))
        self.private_key = _clean(private_key or os.getenv("FOUR_OVER_PRIVATE_KEY"))
        self.timeout = timeout

        if not self.apikey or not self.private_key:
            raise ValueError("4over API credentials missing")

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        path = "/" + path.lstrip("/")
        url = f"{self.base_url}{path}"

        sig = fourover_signature(self.private_key, method)
        query = dict(params or {})

        headers = {}
        if method in ("GET", "DELETE"):
            query["apikey"] = self.apikey
            query["signature"] = sig
        else:
            headers["Authorization"] = f"API {self.apikey}:{sig}"

        r = requests.request(
            method=method,
            url=url,
            params=query,
            headers=headers,
            timeout=self.timeout,
        )

        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}

        return {
            "http_status": r.status_code,
            "ok": r.ok,
            "data": payload,
            "debug": {
                "url": url,
                "method": method,
                "query": {**query, "signature": f"{sig[:6]}...{sig[-6:]}"},
            },
        }
# --- ADD THIS AT THE BOTTOM OF fourover_client.py ---

import os

def get_client_from_env():
    """
    Standardized factory used by main.py.
    Reuses the existing FourOverClient implementation.
    """
    api_key = os.getenv("FOUROVER_APIKEY") or os.getenv("FOUR_OVER_APIKEY")
    private_key = os.getenv("FOUROVER_PRIVATE_KEY") or os.getenv("FOUR_OVER_PRIVATE_KEY")

    if not api_key or not private_key:
        raise RuntimeError("Missing 4over credentials in env vars")

    return FourOverClient(
        apikey=api_key,
        private_key=private_key,
    )
