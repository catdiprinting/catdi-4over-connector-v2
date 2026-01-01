# fourover_client.py
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests


# -------------------------
# Errors
# -------------------------

class FourOverError(Exception):
    """Base error for 4over client."""
    pass


class FourOverAuthError(FourOverError):
    """Raised when authentication fails (401/403)."""
    pass


class FourOverHTTPError(FourOverError):
    """Raised for non-auth HTTP errors."""
    def __init__(self, status_code: int, message: str, url: str, body: str = ""):
        super().__init__(f"{status_code} {message} url={url} body={body[:500]}")
        self.status_code = status_code
        self.url = url
        self.body = body


# -------------------------
# Client
# -------------------------

@dataclass
class FourOverClient:
    base_url: str
    public_key: str
    private_key: str
    timeout: int = 30
    user_agent: str = "catdi-4over-connector/1.0"

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("base_url is required")
        if not self.public_key:
            raise ValueError("public_key is required")
        if not self.private_key:
            raise ValueError("private_key is required")

        # IMPORTANT:
        # 4over "API Key Authentication" signature for GET/DELETE is:
        # signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))
        # NOTE: signature does NOT include path or query string. :contentReference[oaicite:1]{index=1}
        self._derived_key_hex = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})

    # ---------- auth helpers ----------

    def signature_for_method(self, method: str) -> str:
        method_up = method.upper().strip()
        return hmac.new(
            self._derived_key_hex.encode("utf-8"),
            method_up.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def build_get_delete_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        if not path.startswith("/"):
            path = "/" + path

        q: Dict[str, Any] = {}
        if params:
            q.update(params)

        # add auth params
        q["apikey"] = self.public_key
        q["signature"] = self.signature_for_method("GET")  # GET/DELETE use query auth signature

        # keep it stable
        qs = urlencode(q, doseq=True)
        return f"{self.base_url}{path}?{qs}"

    def build_headers_for_write(self, method: str) -> Dict[str, str]:
        # POST/PUT/PATCH: use Authorization header per docs. :contentReference[oaicite:2]{index=2}
        sig = self.signature_for_method(method)
        return {"Authorization": f"API {self.public_key}:{sig}"}

    # ---------- request core ----------

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Any = None,
        retries: int = 2,
        backoff_s: float = 0.6,
    ) -> Tuple[int, str, Any, str]:
        """
        Returns: (status_code, url, parsed_json_or_text, raw_text)
        """
        method_up = method.upper().strip()

        if method_up in ("GET", "DELETE"):
            url = self.build_get_delete_url(path, params=params)
            headers = {}
        elif method_up in ("POST", "PUT", "PATCH"):
            # For write methods, auth is in Authorization header
            if not path.startswith("/"):
                path = "/" + path
            url = f"{self.base_url}{path}"
            headers = self.build_headers_for_write(method_up)
        else:
            raise ValueError(f"Unsupported method: {method_up}")

        last_exc: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                resp = self._session.request(
                    method_up,
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    params=None if method_up in ("GET", "DELETE") else params,
                    json=json,
                    data=data,
                )
                raw = resp.text or ""

                # Auth errors
                if resp.status_code in (401, 403):
                    raise FourOverAuthError(raw[:800])

                # Other errors
                if resp.status_code >= 400:
                    raise FourOverHTTPError(
                        status_code=resp.status_code,
                        message="4over_http_error",
                        url=url,
                        body=raw,
                    )

                # Parse JSON if possible
                try:
                    parsed = resp.json()
                except Exception:
                    parsed = raw

                return resp.status_code, url, parsed, raw

            except (requests.RequestException, FourOverHTTPError, FourOverAuthError) as e:
                last_exc = e

                # Retry only on network-ish errors or 5xx
                retryable = isinstance(e, requests.RequestException)
                if isinstance(e, FourOverHTTPError) and 500 <= e.status_code <= 599:
                    retryable = True

                if attempt >= retries or not retryable:
                    raise

                time.sleep(backoff_s * (2 ** attempt))

        # should never get here
        raise FourOverError(f"Request failed: {last_exc}")

    # ---------- convenience endpoints ----------

    def whoami(self) -> Any:
        _, _, parsed, _ = self.request("GET", "/whoami")
        return parsed

    def get_categories(self, max_: int = 1000, offset: int = 0) -> Any:
        # pagination is max/offset per docs :contentReference[oaicite:3]{index=3}
        params = {"max": max_, "offset": offset}
        _, _, parsed, _ = self.request("GET", "/printproducts/categories", params=params)
        return parsed

    def get_category_products(self, category_uuid: str, max_: int = 1000, offset: int = 0) -> Any:
        params = {"max": max_, "offset": offset}
        _, _, parsed, _ = self.request(
            "GET",
            f"/printproducts/categories/{category_uuid}/products",
            params=params,
        )
        return parsed


# ---------- factory from env ----------

def from_env() -> FourOverClient:
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").strip()
    public_key = os.getenv("FOUR_OVER_APIKEY", "").strip()
    private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

    # Reminder: DO NOT strip internal characters. Only trim outer whitespace.
    private_key = private_key.strip()

    return FourOverClient(
        base_url=base_url,
        public_key=public_key,
        private_key=private_key,
        timeout=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
    )
