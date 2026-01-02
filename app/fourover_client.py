import hashlib
import hmac
import time
import requests
from urllib.parse import urlparse
from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        # Normalize + strip secrets (Railway env vars can include trailing newlines/spaces)
        self.base = (FOUR_OVER_BASE_URL or "").rstrip("/")
        self.apikey = (FOUR_OVER_APIKEY or "").strip()
        self.private_key = (FOUR_OVER_PRIVATE_KEY or "").strip().encode("utf-8")

    def _sign(self, canonical: str) -> str:
        """
        4over signature is HMAC-SHA256(private_key, canonical_string)
        """
        digest = hmac.new(self.private_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return digest

    def _request(self, method: str, path: str, params=None):
        params = params or {}

        # 4over signing: include apikey in the canonical string.
        # IMPORTANT: Do NOT add extra params (like timestamp) unless 4over explicitly requires them,
        # otherwise their server-side signature validation will fail.
        params["apikey"] = self.apikey

        # Canonical string is path + '?' + sorted query string (apikey & timestamp included)
        # We'll build it the same way the request URL is built.
        # NOTE: requests will encode params. We keep it simple and stable by sorting.
        items = sorted(params.items(), key=lambda x: x[0])
        query = "&".join([f"{k}={v}" for k, v in items])
        canonical = f"{path}?{query}"

        sig = self._sign(canonical)
        params["signature"] = sig

        url = f"{self.base}{path}"

        resp = requests.request(method, url, params=params, timeout=FOUR_OVER_TIMEOUT)
        return resp.status_code, resp.json() if resp.content else None

    def get(self, path: str, params=None):
        return self._request("GET", path, params=params)

    def get_by_full_url(self, full_url: str, params=None):
        """
        If 4over returns a full URL in payload, use it safely.
        """
        u = urlparse(full_url)
        return self.get(u.path, params=params)
