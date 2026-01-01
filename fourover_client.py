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
    apikey: str
    private_key: str
    timeout_seconds: int = 30

    @staticmethod
    def from_env() -> "FourOverConfig":
        base_url = (os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").strip().rstrip("/")
        apikey = (os.getenv("FOUR_OVER_APIKEY") or "").strip()
        private_key = (os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip()
        timeout_seconds_raw = (os.getenv("FOUR_OVER_TIMEOUT") or "30").strip()

        try:
            timeout_seconds = int(timeout_seconds_raw)
        except ValueError:
            timeout_seconds = 30

        if not apikey:
            raise FourOverError("Missing env var FOUR_OVER_APIKEY")
        if not private_key:
            raise FourOverError("Missing env var FOUR_OVER_PRIVATE_KEY")

        return FourOverConfig(
            base_url=base_url,
            apikey=apikey,
            private_key=private_key,
            timeout_seconds=timeout_seconds,
        )


class FourOverClient:
    """
    Backwards compatible constructor supports:
      - apikey=...
      - public_key=... (alias for apikey)
      - timeout_seconds=...
      - timeout=... (alias for timeout_seconds)

    Signature approach here matches what you were using in v2:
      signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key).hexdigest())
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        apikey: Optional[str] = None,
        public_key: Optional[str] = None,  # alias
        private_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        timeout: Optional[int] = None,  # alias
    ):
        if apikey is None and public_key is not None:
            apikey = public_key
        if timeout_seconds is None and timeout is not None:
            timeout_seconds = timeout

        # fall back to env if values not provided
        env = FourOverConfig.from_env()

        self.base_url = (base_url or env.base_url).strip().rstrip("/")
        self.apikey = (apikey or env.apikey).strip()
        self.private_key = (private_key or env.private_key).strip()
        self.timeout_seconds = int(timeout_seconds or env.timeout_seconds)

        # key is SHA256(private_key).hexdigest() as string
        self._hashed_private_hex = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()

        self.session = requests.Session()

    def _signature_for_method(self, method: str) -> str:
        msg = method.upper().encode("utf-8")
        key = self._hashed_private_hex.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

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

        url = f"{self.base_url}{path}"

        req_params = dict(params or {})
        req_headers = dict(headers or {})

        if method_u in ("GET", "DELETE"):
            req_params["apikey"] = self.apikey
            req_params["signature"] = self._signature_for_method(method_u)
        elif method_u in ("POST", "PUT", "PATCH"):
            sig = self._signature_for_method(method_u)
            req_headers["Authorization"] = f"API {self.apikey}:{sig}"
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
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as e:
            raise FourOverHTTPError(f"Network error calling 4over: {e}") from e

        content_type = (resp.headers.get("content-type") or "").lower()
        parsed: Any = None
        if "application/json" in content_type:
            try:
                parsed = resp.json()
            except Exception:
                parsed = None

        if resp.status_code in (401, 403):
            raise FourOverAuthError(
                f"Auth failed ({resp.status_code}) {method_u} {url} :: "
                f"{parsed if parsed is not None else resp.text}"
            )

        if resp.status_code >= 400:
            raise FourOverHTTPError(
                f"HTTP error ({resp.status_code}) {method_u} {url} :: "
                f"{parsed if parsed is not None else resp.text}"
            )

        return parsed if parsed is not None else resp.text

    def whoami(self) -> Any:
        return self.request("GET", "/whoami")
