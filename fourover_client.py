"""
fourover_client.py

Backwards-compatible FourOverClient supporting:
- FourOverClient()
- FourOverClient(config=FourOverConfig(...))
- FourOverClient(base_url=..., apikey=..., private_key=..., timeout_seconds=...)
- Legacy args supported:
    public_key (alias of apikey)
    timeout (alias of timeout_seconds)

4over Authentication per docs (as implemented here):
- GET/DELETE: apikey + signature in query
- POST/PUT/PATCH: Authorization header "API {apikey}:{signature}"
- signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key).hexdigest())
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

import requests


class FourOverError(Exception):
    pass


class FourOverAuthError(FourOverError):
    pass


class FourOverHTTPError(FourOverError):
    pass


@dataclass(frozen=True)
class FourOverConfig:
    base_url: str
    public_key: str
    private_key: str
    timeout_seconds: int = 30

    @staticmethod
    def from_env() -> "FourOverConfig":
        base_url = (os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").strip().rstrip("/")
        public_key = (os.getenv("FOUR_OVER_APIKEY") or "").strip()
        private_key = (os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip()
        timeout_seconds = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

        if not public_key:
            raise FourOverError("Missing env var FOUR_OVER_APIKEY")
        if not private_key:
            raise FourOverError("Missing env var FOUR_OVER_PRIVATE_KEY")

        return FourOverConfig(
            base_url=base_url,
            public_key=public_key,
            private_key=private_key,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def from_values(
        *,
        base_url: Optional[str] = None,
        apikey: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> "FourOverConfig":
        b = (base_url or os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").strip().rstrip("/")
        k = (apikey or os.getenv("FOUR_OVER_APIKEY") or "").strip()
        pk = (private_key or os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip()
        t = int(timeout_seconds or os.getenv("FOUR_OVER_TIMEOUT", "30"))

        if not k:
            raise FourOverError("Missing apikey / FOUR_OVER_APIKEY")
        if not pk:
            raise FourOverError("Missing private_key / FOUR_OVER_PRIVATE_KEY")

        return FourOverConfig(base_url=b, public_key=k, private_key=pk, timeout_seconds=t)


class FourOverClient:
    def __init__(
        self,
        config: Optional[FourOverConfig] = None,
        *,
        base_url: Optional[str] = None,
        apikey: Optional[str] = None,
        public_key: Optional[str] = None,        # legacy alias
        private_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        timeout: Optional[int] = None,           # legacy alias
    ):
        # normalize legacy aliases
        if apikey is None and public_key is not None:
            apikey = public_key
        if timeout_seconds is None and timeout is not None:
            timeout_seconds = timeout

        if config is None:
            if base_url is not None or apikey is not None or private_key is not None or timeout_seconds is not None:
                config = FourOverConfig.from_values(
                    base_url=base_url,
                    apikey=apikey,
                    private_key=private_key,
                    timeout_seconds=timeout_seconds,
                )
            else:
                config = FourOverConfig.from_env()

        self.config = config
        self.session = requests.Session()

        # docs-style: HMAC key = sha256(private_key) hex digest (string)
        self._hashed_private_hex = hashlib.sha256(self.config.private_key.encode("utf-8")).hexdigest()

    def _signature_for_method(self, method: str) -> str:
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

    # Convenience helpers (what your main.py expects)
    def get(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Any] = None) -> Any:
        return self.request("POST", path, params=params, json=json)

    def whoami(self) -> Any:
        return self.get("/whoami")
