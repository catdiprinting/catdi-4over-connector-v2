import hashlib
import hmac
import os
from typing import Any, Dict, Optional

import requests


def _clean_secret(value: str) -> str:
    # Removes invisible copy/paste junk (spaces/newlines) that breaks signatures
    return (value or "").strip()


def fourover_signature(private_key: str, http_method: str) -> str:
    """
    4over signature (per their docs / examples):
      key = sha256(private_key).hexdigest()
      signature = hmac_sha256(key, HTTP_METHOD).hexdigest()

    Notes:
    - HTTP_METHOD must be "GET", "POST", etc. (not a URL path)
    - We use the hex digest of sha256(private_key) as the HMAC key bytes (utf-8)
    """
    pk = _clean_secret(private_key).encode("utf-8")
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

        # GET/DELETE -> signature in QUERY
        if method in ("GET", "DELETE"):
            params_out["apikey"] = self.apikey
            params_out["signature"] = sig
        else:
            # POST/PUT/PATCH -> Authorization header
            headers["Authorization"] = f"API {self.apikey}:{sig}"

        r = requests.request(
            method=method,
            url=url,
            params=params_out,
            json=json,
            headers=headers,
            timeout=self.timeout,
        )

        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}

        # Safe debug: do NOT leak full signature
        safe_sig = f"{sig[:6]}...{sig[-6:]} (len={len(sig)})"

        dbg_query = dict(params_out)
        if "signature" in dbg_query:
            dbg_query["signature"] = safe_sig

        return {
            "http_status": r.status_code,
            "ok": r.ok,
            "data": payload,
            "debug": {
                "url": url,
                "method": method,
                "query": dbg_query,
                "auth_header": "present" if "Authorization" in headers else None,
            },
        }
    def whoami(self) -> Dict[str, Any]:
        return self.request("GET", "/whoami")

    def list_products(self, limit: int = 300) -> Dict[str, Any]:
        """
        Best-effort endpoint. If 4over uses a different path in your account,
        we can adjust once you show me the response body / docs excerpt.
        """
        # Common guess: /products
        return self.request("GET", "/products", params={"limit": limit})
