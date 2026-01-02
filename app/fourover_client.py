# app/fourover_client.py
import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional
import requests


class FourOverClient:
    """
    Minimal 4over REST client using apikey + HMAC signature.

    IMPORTANT:
    - We do NOT raise at import/startup if env vars are missing.
    - We validate right before making a request so the app can boot even if env is misconfigured.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout: int = 60,
    ):
        self.base_url = (base_url or os.getenv("FOUR_OVER_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("FOUR_OVER_APIKEY")
        self.private_key = private_key or os.getenv("FOUR_OVER_PRIVATE_KEY")
        self.timeout = timeout

    def _require_config(self):
        if not self.base_url:
            raise RuntimeError("Missing FOUR_OVER_BASE_URL")
        if not self.api_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY")
        if not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_PRIVATE_KEY")

    def _sign(self, canonical: str) -> str:
        # 4over signature = HMAC-SHA256(private_key, canonical)
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request(self, method: str, path_or_url: str, params: Optional[dict] = None) -> Dict[str, Any]:
        self._require_config()

        # Accept either "/whoami" or full URL from API payloads
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
            # canonical should be only path + query string (without domain)
            # Example: https://api.4over.com/whoami?apikey=...
            # We rebuild canonical from parsed URL.
            from urllib.parse import urlparse

            parsed = urlparse(url)
            path = parsed.path
        else:
            path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
            url = f"{self.base_url}{path}"

        params = dict(params or {})
        params["apikey"] = self.api_key

        # canonical = path + '?' + sorted querystring (apikey included)
        # requests will encode query; we build our own canonical ordering.
        from urllib.parse import urlencode

        canonical_qs = urlencode(sorted(params.items()), doseq=True)
        canonical = f"{path}?{canonical_qs}"

        signature = self._sign(canonical)
        params["signature"] = signature

        r = requests.request(method, url, params=params, timeout=self.timeout)
        # 4over often returns JSON; if not JSON, raise with text
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}

        if r.status_code >= 400:
            return {"ok": False, "http_code": r.status_code, "response": payload, "debug": {"url": r.url, "canonical": canonical}}
        return {"ok": True, "http_code": r.status_code, "data": payload, "debug": {"url": r.url, "canonical": canonical}}

    def get(self, path_or_url: str, params: Optional[dict] = None) -> Dict[str, Any]:
        return self.request("GET", path_or_url, params=params)
