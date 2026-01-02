from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

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
    apikey: str
    private_key: str
    timeout_seconds: int = 30
    api_prefix: str = ""  # e.g. "" or "/printproducts"

    @staticmethod
    def from_env() -> "FourOverConfig":
        def s(name: str, default: str = "") -> str:
            v = os.getenv(name)
            return default if v is None else v.strip()

        def i(name: str, default: int) -> int:
            raw = s(name, "")
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        base_url = s("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        apikey = s("FOUR_OVER_APIKEY", "")
        private_key = s("FOUR_OVER_PRIVATE_KEY", "")
        timeout_seconds = i("FOUR_OVER_TIMEOUT", 30)

        # This lets us adapt quickly if 4over endpoints are under /printproducts
        api_prefix = s("FOUR_OVER_API_PREFIX", "").strip()
        if api_prefix and not api_prefix.startswith("/"):
            api_prefix = "/" + api_prefix
        api_prefix = api_prefix.rstrip("/")

        if not apikey:
            raise FourOverError("Missing FOUR_OVER_APIKEY")
        if not private_key:
            raise FourOverError("Missing FOUR_OVER_PRIVATE_KEY")

        return FourOverConfig(
            base_url=base_url,
            apikey=apikey,
            private_key=private_key,
            timeout_seconds=timeout_seconds,
            api_prefix=api_prefix,
        )


class FourOverClient:
    """
    Signature mode (based on your older v2/PHP trait evidence):
      signature = HMAC_SHA256(method, key=SHA256(private_key).hexdigest())

    GET/DELETE: apikey + signature in query params
    POST/PUT/PATCH: Authorization: API {apikey}:{signature}

    If 4over requires a different canonical signature, we update ONLY _signature_for_method().
    """

    def __init__(self, config: Optional[FourOverConfig] = None):
        self.config = config or FourOverConfig.from_env()
        self.session = requests.Session()
        self._hashed_private_hex = hashlib.sha256(self.config.private_key.encode("utf-8")).hexdigest()

    def _signature_for_method(self, method: str) -> str:
        msg = method.upper().encode("utf-8")
        key = self._hashed_private_hex.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def _full_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        # apply optional prefix such as /printproducts
        if self.config.api_prefix:
            return f"{self.config.api_prefix}{path}"
        return path

    def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Any = None) -> Any:
        m = method.upper()
        full_path = self._full_path(path)
        url = f"{self.config.base_url}{full_path}"

        req_params = dict(params or {})
        req_headers: Dict[str, str] = {}

        if m in ("GET", "DELETE"):
            req_params["apikey"] = self.config.apikey
            req_params["signature"] = self._signature_for_method(m)
        elif m in ("POST", "PUT", "PATCH"):
            sig = self._signature_for_method(m)
            req_headers["Authorization"] = f"API {self.config.apikey}:{sig}"
        else:
            raise FourOverError(f"Unsupported method: {m}")

        try:
            resp = self.session.request(
                method=m,
                url=url,
                params=req_params,
                json=json,
                headers=req_headers,
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as e:
            raise FourOverHTTPError(f"Network error: {e}") from e

        ct = (resp.headers.get("content-type") or "").lower()
        data: Any = None
        if "application/json" in ct:
            try:
                data = resp.json()
            except Exception:
                data = None

        if resp.status_code in (401, 403):
            raise FourOverAuthError(f"Auth failed {resp.status_code} {m} {url}: {data if data is not None else resp.text}")

        if resp.status_code >= 400:
            raise FourOverHTTPError(f"HTTP {resp.status_code} {m} {url}: {data if data is not None else resp.text}")

        return data if data is not None else resp.text

    def get(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, params: Optional[Dict[str, Any]] = None, json: Any = None) -> Any:
        return self.request("POST", path, params=params, json=json)
