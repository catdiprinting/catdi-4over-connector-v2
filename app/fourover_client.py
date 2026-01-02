import hmac
import hashlib
import requests
from urllib.parse import urlencode, urlparse

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)

class FourOverClient:
    """
    Deterministic URL building:
      - base_url: https://api.4over.com
      - catalog endpoints live under /printproducts/...
      - whoami lives at /whoami (no prefix)
    Deterministic signing:
      signature = HMAC-SHA256(private_key, canonical_path_with_query_without_signature)
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        self.base_url = FOUR_OVER_BASE_URL.rstrip("/")
        self.prefix = FOUR_OVER_API_PREFIX.strip("/")
        self.apikey = FOUR_OVER_APIKEY
        self.private_key = FOUR_OVER_PRIVATE_KEY
        self.timeout = FOUR_OVER_TIMEOUT

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _build(self, path: str, params: dict | None, use_prefix: bool) -> tuple[str, str]:
        """
        Returns (full_url, canonical_to_sign)
        """
        if not path.startswith("/"):
            path = "/" + path

        if use_prefix:
            api_path = f"/{self.prefix}{path}"
        else:
            api_path = path

        qp = dict(params or {})
        qp["apikey"] = self.apikey

        canonical = api_path
        if qp:
            canonical = f"{api_path}?{urlencode(qp, doseq=True)}"

        sig = self._sign(canonical)

        qp["signature"] = sig
        full_url = f"{self.base_url}{api_path}?{urlencode(qp, doseq=True)}"
        return full_url, canonical

    def get(self, path: str, params: dict | None = None, use_prefix: bool = True):
        url, canonical = self._build(path, params, use_prefix=use_prefix)
        r = requests.get(url, timeout=self.timeout)
        return r.status_code, url, canonical, r

    def post(self, path: str, payload: dict | None = None, params: dict | None = None, use_prefix: bool = True):
        url, canonical = self._build(path, params, use_prefix=use_prefix)
        r = requests.post(url, json=payload or {}, timeout=self.timeout)
        return r.status_code, url, canonical, r
