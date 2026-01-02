import hashlib
import hmac
from urllib.parse import urlencode, urlparse, parse_qsl

import requests

from .config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    """
    4over REST client (matches 4over docs).

    AUTH RULES (per docs):
    - Signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
    - GET/DELETE: pass apikey + signature in query string
    - POST/PUT/PATCH: send header: Authorization: API {PUBLIC_KEY}:{SIGNATURE}

    IMPORTANT ABOUT YOUR ENV:
    - FOUR_OVER_API_PREFIX is "printproducts" for catalog endpoints
    - /whoami is ROOT (no /printproducts prefix)
    """

    def __init__(
        self,
        base_url: str | None = None,
        apikey: str | None = None,
        private_key: str | None = None,
        api_prefix: str | None = None,
        timeout: int | None = None,
    ):
        # allow main.py to pass args; fall back to env config
        self.base = (base_url or FOUR_OVER_BASE_URL or "https://api.4over.com").rstrip("/")
        self.apikey = apikey if apikey is not None else FOUR_OVER_APIKEY
        self.private_key = private_key if private_key is not None else FOUR_OVER_PRIVATE_KEY
        self.prefix = (api_prefix if api_prefix is not None else FOUR_OVER_API_PREFIX).strip("/")
        self.timeout = int(timeout if timeout is not None else FOUR_OVER_TIMEOUT)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "catdi-4over-connector",
            }
        )

    # -------------------------
    # Signature (DOC-CORRECT)
    # -------------------------
    def _hmac_key(self) -> bytes:
        # key = SHA256(private_key) as bytes
        return hashlib.sha256((self.private_key or "").encode("utf-8")).digest()

    def _signature_for_method(self, method: str) -> str:
        # signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
        return hmac.new(self._hmac_key(), method.upper().encode("utf-8"), hashlib.sha256).hexdigest()

    # -------------------------
    # Prefix logic (YOUR SETUP)
    # -------------------------
    def _should_prefix(self, path: str) -> bool:
        # /whoami is root endpoint (no prefix)
        if path.startswith("/whoami"):
            return False
        # already prefixed
        if self.prefix and path.startswith(f"/{self.prefix}/"):
            return False
        return bool(self.prefix)

    def _with_prefix(self, path: str) -> str:
        if self._should_prefix(path):
            return f"/{self.prefix}{path}"
        return path

    def _build_url_for_get(self, path: str, params: dict | None = None) -> tuple[str, dict]:
        if not path.startswith("/"):
            path = "/" + path

        path = self._with_prefix(path)

        q = dict(params or {})
        q["apikey"] = self.apikey
        q["signature"] = self._signature_for_method("GET")

        url = f"{self.base}{path}"
        return url, q

    # -------------------------
    # Public helpers
    # -------------------------
    def get(self, path: str, params: dict | None = None):
        """
        Returns parsed JSON (dict) on success when 4over returns JSON.
        Returns a consistent error object on failure.
        """
        if not self.apikey or not self.private_key:
            return {
                "status": "error",
                "status_code": 500,
                "status_text": "Missing Credentials",
                "message": "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY",
            }

        url, q = self._build_url_for_get(path, params)

        r = self.session.get(url, params=q, timeout=self.timeout)
        ct = (r.headers.get("content-type") or "").lower()

        if r.ok:
            return r.json() if "application/json" in ct else r.text

        # failure: return useful debug (no crashing)
        body = None
        try:
            body = r.json() if "application/json" in ct else r.text
        except Exception:
            body = r.text

        return {
            "status": "error",
            "status_code": r.status_code,
            "status_text": r.reason,
            "message": "4over request failed",
            "debug": {
                "url": r.url,
                "base": self.base,
                "prefix": self.prefix,
                "path_requested": path,
                "signature_method": "HMAC_SHA256(HTTP_METHOD, SHA256(private_key))",
            },
            "current_content": body,
        }

    def get_by_full_url(self, full_url: str):
        """
        If 4over returns a full URL in its payload, you can call it here.
        We re-sign using GET method-only signature and keep query params.
        """
        if not self.apikey or not self.private_key:
            return {
                "status": "error",
                "status_code": 500,
                "status_text": "Missing Credentials",
                "message": "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY",
            }

        parsed = urlparse(full_url)
        path = parsed.path
        params = dict(parse_qsl(parsed.query))

        # force our apikey + signature
        params.pop("signature", None)
        params["apikey"] = self.apikey
        params["signature"] = self._signature_for_method("GET")

        url = f"{self.base}{path}"
        r = self.session.get(url, params=params, timeout=self.timeout)
        ct = (r.headers.get("content-type") or "").lower()

        if r.ok:
            return r.json() if "application/json" in ct else r.text

        body = None
        try:
            body = r.json() if "application/json" in ct else r.text
        except Exception:
            body = r.text

        return {
            "status": "error",
            "status_code": r.status_code,
            "status_text": r.reason,
            "message": "4over request failed",
            "debug": {"url": r.url},
            "current_content": body,
        }
