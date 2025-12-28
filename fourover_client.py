# fourover_client.py
import hashlib
import hmac
import os
from typing import Any, Dict, Optional

import requests


def _clean_secret(value: str) -> str:
    # Removes invisible copy/paste junk that breaks signatures
    return (value or "").strip()


def fourover_signature(private_key: str, http_method: str) -> str:
    """
    4over signature (per their docs):
      key = sha256(private_key).hexdigest()
      signature = hmac_sha256(key, HTTP_METHOD).hexdigest()
    """
    pk = _clean_secret(private_key).encode("utf-8")

    # sha256(private_key) -> hex digest string
    pk_hash_hex = hashlib.sha256(pk).hexdigest().encode("utf-8")

    msg = http_method.upper().encode("utf-8")
    return hmac.new(pk_hash_hex, msg, hashlib.sha256).hexdigest()


class FourOverClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        apikey: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (base_url or os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").rstrip("/")
        self.apikey = _clean_secret(apikey or os.getenv("FOUR_OVER_APIKEY") or "")
        self.private_key = _clean_secret(private_key or os.getenv("FOUR_OVER_PRIVATE_KEY") or "")
        self.timeout = timeout

        if not self.apikey:
            raise ValueError("FOUR_OVER_APIKEY is missing")
        if not self.private_key:
            raise ValueError("FOUR_OVER_PRIVATE_KEY is missing")

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        path = "/" + path.lstrip("/")
        url = f"{self.base_url}{path}"

        sig = fourover_signature(self.private_key, method)

        params_out = dict(params or {})
        headers: Dict[str, str] = {}

        # ✅ IMPORTANT: 4over GET/DELETE expects apikey + signature in QUERY
        if method in ("GET", "DELETE"):
            params_out["apikey"] = self.apikey
            params_out["signature"] = sig
        else:
            # ✅ For POST/PUT/PATCH, docs show Authorization header
            headers["Authorization"] = f"API {self.apikey}:{sig}"

        r = requests.request(
            method=method,
            url=url,
            params=params_out,
            json=json,
            headers=headers,
            timeout=self.timeout,
        )

        # Try JSON, fallback to text
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
                # Safe debug: show that signature exists without leaking it
                "query": {
                    **({k: v for k, v in params_out.items() if k != "signature"}),
                    "signature": f"{sig[:6]}...{sig[-6:]} (len={len(sig)})" if "signature" in params_out else None,
                },
                "auth_header": "present" if "Authorization" in headers else None,
            },
        }
