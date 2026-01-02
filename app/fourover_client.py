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
    Thin 4over REST client.

    Key points:
    - /whoami is NOT under /printproducts
    - Signature = HMAC-SHA256(private_key, canonical_path_with_query_without_signature)
    - Avoid double-prefixing /printproducts/printproducts/...
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            # Don't crash import; endpoints will show missing in /debug/auth
            pass
        self.base = FOUR_OVER_BASE_URL.rstrip("/")
        self.prefix = FOUR_OVER_API_PREFIX.strip("/")

    def _should_prefix(self, path: str) -> bool:
        # whoami is root endpoint
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

    def _canonical(self, path: str, params: dict) -> str:
        # canonical includes apikey and ANY other params (sorted), but NOT signature
        canonical_params = dict(params or {})
        canonical_params["apikey"] = FOUR_OVER_APIKEY

        # sort params for stable canonical
        qs = urlencode(sorted(canonical_params.items()))
        return f"{path}?{qs}"

    def _signature(self, canonical: str) -> str:
        return hmac.new(
            FOUR_OVER_PRIVATE_KEY.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_url(self, path: str, params: dict | None = None) -> str:
        # prefix only for catalog endpoints
        path = self._with_prefix(path)

        canonical = self._canonical(path, params or {})
        sig = self._signature(canonical)

        final_params = dict(params or {})
        final_params["apikey"] = FOUR_OVER_APIKEY
        final_params["signature"] = sig

        return f"{self.base}{path}?{urlencode(final_params)}"

    def get(self, path: str, params: dict | None = None):
        url = self._build_url(path, params)
        r = requests.get(url, timeout=FOUR_OVER_TIMEOUT)
        ct = r.headers.get("content-type", "")
        data = r.json() if "application/json" in ct else r.text
        return {"ok": r.ok, "http_code": r.status_code, "url": url, "data": data}

    def get_by_full_url(self, full_url: str):
        # If 4over returns full URLs (already prefixed), use them as-is.
        parsed = urlparse(full_url)
        path = parsed.path
        params = dict(parse_qsl(parsed.query))

        # remove signature if present
        params.pop("signature", None)
        params.pop("apikey", None)

        # build signature for the path + params (and apikey added in _canonical)
        canonical = self._canonical(path, params)
        sig = self._signature(canonical)

        params["apikey"] = FOUR_OVER_APIKEY
        params["signature"] = sig

        url = f"{self.base}{path}?{urlencode(params)}"
        r = requests.get(url, timeout=FOUR_OVER_TIMEOUT)
        ct = r.headers.get("content-type", "")
        data = r.json() if "application/json" in ct else r.text
        return {"ok": r.ok, "http_code": r.status_code, "url": url, "data": data}
