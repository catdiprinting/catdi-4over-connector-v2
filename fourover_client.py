"""
fourover_client.py (ROOT FOLDER)

Implements 4over API Key Authentication per 4over docs:

- GET/DELETE: pass apikey + signature in querystring
  ?apikey={PUBLIC_KEY}&signature={SIGNATURE}

- POST/PUT/PATCH: pass Authorization header
  Authorization: API {PUBLIC_KEY}:{SIGNATURE}

Signature generation:
- signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))
  (i.e., depends on HTTP method ONLY)

Docs: https://api-users.4over.com/?page_id=44
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

import requests


# -------------------------
# Errors
# -------------------------

class FourOverError(Exception):
    """Base error for all 4over client exceptions."""


class FourOverAuthError(FourOverError):
    """Authentication/authorization failure (401/403)."""


class FourOverHTTPError(FourOverError):
    """Non-auth HTTP error from 4over."""


# -------------------------
# Config
# -------------------------

@dataclass(frozen=True)
class FourOverConfig:
    base_url: str
    public_key: str
    private_key: str
    timeout_seconds: int = 30

    @staticmethod
    def from_env() -> "FourOverConfig":
        base_url = (os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").strip()
        public_key = (os.getenv("FOUR_OVER_APIKEY") or "").strip()
        private_key = (os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip()

        if not public_key:
            raise FourOverError("Missing env var FOUR_OVER_APIKEY")
        if not private_key:
            raise FourOverError("Missing env var FOUR_OVER_PRIVATE_KEY")

        # normalize base url
        base_url = base_url.rstrip("/")

        return FourOverConfig(
            base_url=base_url,
            public_key=public_key,
            private_key=private_key,
            timeout_seconds=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
        )


# -------------------------
# Client
# -------------------------

class FourOverClient:
    def __init__(self, config: Optional[FourOverConfig] = None):
        self.config = config or FourOverConfig.from_env()
        self.session = requests.Session()

        # Pre-hash the private key ONE time:
        # docs show: hash('sha256', $myPrivateKey) used as the HMAC key
        self._hashed_private_hex = hashlib.sha256(
            self.config.private_key.encode("utf-8")
        ).hexdigest()

    def _signature_for_method(self, method: str) -> str:
        """
        4over signature:
          signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))

        Note: In PHP docs, key is the hex string from sha256(private_key).
        We'll use that same hex string as bytes here.
        """
        msg = method.upper().encode("utf-8")
        key = self._hashed_private_hex.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def _auth_params_for_get_delete(self, method: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        p = dict(params or {})
        p["apikey"] = self.config.public_key
        p["signature"] = self._signature_for_method(method)
        return p

    def _auth_headers_for_write(self, method: str, headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        h = dict(headers or {})
        sig = self._signature_for_method(method)
        # docs: "Authorization: API {PUBLIC_KEY}:{SIGNATURE}"
        h["Authorization"] = f"API {self.config.public_key}:{sig}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        method_u = method.upper()
        if not path.startswith("/"):
            path = "/" + path

        url = f"{self.config.base_url}{path}"

        if method_u in ("GET", "DELETE"):
            req_params = self._auth_params_for_get_delete(method_u, params)
            req_headers = dict(headers or {})
        elif method_u in ("POST", "PUT", "PATCH"):
            req_params = dict(params or {})
            req_headers = self._auth_headers_for_write(method_u, headers)
        else:
            raise FourOverError(f"Unsupported HTTP method: {method_u}")

        try:
            resp = self.session.request(
                method=method_u,
                url=url,
                params=req_params,
                json=json,
                data=data,
                headers=req_headers,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as e:
            raise FourOverHTTPError(f"Network error calling 4over: {e}") from e

        # Try parse JSON, but don’t assume it always is
        content_type = (resp.headers.get("content-type") or "").lower()
        body_text = resp.text

        parsed: Any = None
        if "application/json" in content_type:
            try:
                parsed = resp.json()
            except Exception:
                parsed = None

        if resp.status_code in (401, 403):
            raise FourOverAuthError(
                f"4over auth failed ({resp.status_code}) for {method_u} {url}. "
                f"Response: {parsed if parsed is not None else body_text}"
            )

        if resp.status_code >= 400:
            raise FourOverHTTPError(
                f"4over http error ({resp.status_code}) for {method_u} {url}. "
                f"Response: {parsed if parsed is not None else body_text}"
            )

        return parsed if parsed is not None else body_text

    # Convenience endpoints
    def whoami(self) -> Any:
        # docs show /whoami for auth test
        return self.request("GET", "/whoami")

    def get_categories(self) -> Any:
        # per docs: GET/printproducts/categories
        return self.request("GET", "/printproducts/categories")


# Optional: tiny self-test helper (won’t run unless called)
def _debug_signature() -> Dict[str, str]:
    cfg = FourOverConfig.from_env()
    client = FourOverClient(cfg)
    return {
        "base_url": cfg.base_url,
        "public_key_present": bool(cfg.public_key),
        "private_key_len": len(cfg.private_key),
        "sig_get": client._signature_for_method("GET"),
        "sig_post": client._signature_for_method("POST"),
    }
