import hashlib
import hmac
import requests

from .config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    """
    Correct 4over client.
    Signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
    GET requests send apikey + signature as query params.
    """

    def __init__(self):
        self.base = FOUR_OVER_BASE_URL

        self._hmac_key = hashlib.sha256(
            FOUR_OVER_PRIVATE_KEY.encode("utf-8")
        ).digest()

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "catdi-4over-connector",
        })

    def _signature(self, method: str) -> str:
        return hmac.new(
            self._hmac_key,
            method.upper().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def get(self, path: str, params: dict | None = None):
        if not path.startswith("/"):
            path = "/" + path

        query = dict(params or {})
        query["apikey"] = FOUR_OVER_APIKEY
        query["signature"] = self._signature("GET")

        url = f"{self.base}{path}"

        r = self.session.get(
            url,
            params=query,
            timeout=FOUR_OVER_TIMEOUT,
        )

        content_type = r.headers.get("content-type", "")
        data = (
            r.json()
            if "application/json" in content_type.lower()
            else r.text
        )

        return {
            "ok": r.ok,
            "http_code": r.status_code,
            "url": r.url,
            "data": data,
        }


client = FourOverClient()
