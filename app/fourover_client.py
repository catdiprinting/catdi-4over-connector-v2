import hashlib
import hmac
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
    Signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
    GET uses apikey + signature as query params.

    IMPORTANT:
    - ROOT endpoints like /whoami must NOT use /printproducts prefix
    - Catalog endpoints DO use /printproducts prefix
    """

    def __init__(self):
        self.base = FOUR_OVER_BASE_URL
        self.prefix = FOUR_OVER_API_PREFIX  # e.g. "/printproducts" or ""

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "catdi-4over-connector",
        })

    def _require_auth(self):
        if not FOUR_OVER_APIKEY:
            raise RuntimeError("FOUR_OVER_APIKEY is missing/blank.")
        if not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing/blank.")

    def _hmac_key(self) -> bytes:
        # compute on demand so missing key doesn't crash import
        return hashlib.sha256(FOUR_OVER_PRIVATE_KEY.encode("utf-8")).digest()

    def _signature(self, method: str) -> str:
        return hmac.new(
            self._hmac_key(),
            method.upper().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_url(self, path: str, use_prefix: bool) -> str:
        if not path.startswith("/"):
            path = "/" + path
        if use_prefix and self.prefix:
            return f"{self.base}{self.prefix}{path}"
        return f"{self.base}{path}"

    def get(self, path: str, params: dict | None = None, use_prefix: bool = False):
        self._require_auth()

        query = dict(params or {})
        query["apikey"] = FOUR_OVER_APIKEY
        query["signature"] = self._signature("GET")

        url = self._build_url(path, use_prefix=use_prefix)

        r = self.session.get(url, params=query, timeout=FOUR_OVER_TIMEOUT)

        content_type = (r.headers.get("content-type") or "").lower()
        data = r.json() if "application/json" in content_type else r.text

        return {
            "ok": r.ok,
            "http_code": r.status_code,
            "url": r.url,
            "data": data,
        }

client = FourOverClient()
