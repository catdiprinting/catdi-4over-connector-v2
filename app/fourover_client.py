import hashlib
import hmac
import time
import requests
from urllib.parse import urlencode

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    """
    Signs requests like:
      GET /whoami?apikey=XXXX&signature=YYYY
    signature = HMAC-SHA256(private_key, canonical_path_with_query_without_signature)
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY")
        if not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_PRIVATE_KEY")

        self.base = FOUR_OVER_BASE_URL
        self.prefix = ("/" + FOUR_OVER_API_PREFIX.strip("/")) if FOUR_OVER_API_PREFIX else ""
        self.timeout = FOUR_OVER_TIMEOUT

    def _sign(self, canonical: str) -> str:
        # canonical must start with "/"
        digest = hmac.new(
            FOUR_OVER_PRIVATE_KEY.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def _build_url(self, path: str, params: dict | None = None) -> str:
        if not path.startswith("/"):
            path = "/" + path

        full_path = f"{self.prefix}{path}"

        q = params.copy() if params else {}
        q["apikey"] = FOUR_OVER_APIKEY

        # signature is computed WITHOUT signature itself
        canonical = full_path
        if q:
            canonical = canonical + "?" + urlencode(q)

        sig = self._sign(canonical)
        q["signature"] = sig

        return f"{self.base}{full_path}?{urlencode(q)}"

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self._build_url(path, params=params)
        r = requests.get(url, timeout=self.timeout)
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}

        if r.status_code >= 400:
            return {
                "ok": False,
                "http_code": r.status_code,
                "url": url,
                "response": payload,
            }

        return {"ok": True, "url": url, "data": payload}
