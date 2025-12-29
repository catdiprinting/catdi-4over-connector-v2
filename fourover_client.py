import os
import hashlib
import hmac
from urllib.parse import urlencode
import requests


def _clean(s: str) -> str:
    return (s or "").strip()


class FourOverClient:
    """
    Minimal 4over client.

    Railway env vars:
      FOUR_OVER_APIKEY
      FOUR_OVER_PRIVATE_KEY
      FOUR_OVER_BASE_URL (default: https://api.4over.com)

    GET auth is query-string based:
      ?apikey=...&signature=...&max=...&offset=...

    Signature (matches 4over docs/email guidance style):
      hmac_key = sha256(private_key).hexdigest()
      signature = HMAC_SHA256(hmac_key, HTTP_METHOD)

    NOTE: private keys can be short (like X0PHN5KK). That's okay.
    """

    def __init__(self):
        self.api_key = _clean(os.getenv("FOUR_OVER_APIKEY", ""))
        self.private_key = _clean(os.getenv("FOUR_OVER_PRIVATE_KEY", ""))
        self.base_url = _clean(os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")).rstrip("/")

        if not self.api_key:
            raise RuntimeError("Missing env var FOUR_OVER_APIKEY")
        if not self.private_key:
            raise RuntimeError("Missing env var FOUR_OVER_PRIVATE_KEY")

        self.session = requests.Session()
        self.timeout = (5, 30)

    def _signature(self, method: str) -> str:
        method = method.upper()
        hmac_key = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest().encode("utf-8")
        msg = method.encode("utf-8")
        return hmac.new(hmac_key, msg, hashlib.sha256).hexdigest()

    def build_get_url(self, path: str, params: dict | None = None) -> tuple[str, dict]:
        if not path.startswith("/"):
            path = "/" + path

        sig = self._signature("GET")
        merged = {"apikey": self.api_key, "signature": sig, **(params or {})}

        # stable ordering for debugging
        qs = urlencode(sorted((k, str(v)) for k, v in merged.items() if v is not None))

        url = f"{self.base_url}{path}?{qs}"
        debug = {"method": "GET", "path": path, "signature": sig, "url": url, "params": merged}
        return url, debug

    def get(self, path: str, params: dict | None = None):
        url, dbg = self.build_get_url(path, params=params)
        r = self.session.get(url, timeout=self.timeout)
        return r, dbg
