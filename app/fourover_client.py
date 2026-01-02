import hashlib
import hmac
from urllib.parse import urlencode, quote

import requests

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_TIMEOUT,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
)


class FourOverClient:
    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        self.base_url = FOUR_OVER_BASE_URL.rstrip("/")
        self.prefix = (FOUR_OVER_API_PREFIX or "").strip("/")

        self.apikey = FOUR_OVER_APIKEY.strip()
        self.private_key = FOUR_OVER_PRIVATE_KEY.strip()
        self.timeout = int(FOUR_OVER_TIMEOUT)

    def _api_path(self, path: str) -> str:
        """
        whoami lives at root: /whoami
        catalog lives under prefix: /printproducts/...
        """
        if not path.startswith("/"):
            path = "/" + path

        if path.startswith("/whoami"):
            return path

        # If already prefixed, don't double it
        if self.prefix and path.startswith(f"/{self.prefix}/"):
            return path

        if self.prefix:
            return f"/{self.prefix}{path}"
        return path

    def _canonical(self, api_path: str, params: dict | None) -> str:
        """
        Canonical string = "<path>?apikey=...&<params...>"
        apikey FIRST. Do not reorder user-supplied params.
        """
        pairs = [("apikey", self.apikey)]
        if params:
            for k, v in params.items():
                if v is None:
                    continue
                pairs.append((str(k), str(v)))

        qs = urlencode(pairs, quote_via=quote)
        return f"{api_path}?{qs}"

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def get(self, path: str, params: dict | None = None):
        api_path = self._api_path(path)
        canonical = self._canonical(api_path, params)
        signature = self._sign(canonical)

        url = f"{self.base_url}{api_path}"
        r = requests.get(
            url,
            params={"apikey": self.apikey, **(params or {}), "signature": signature},
            timeout=self.timeout,
        )
        return r

    def post(self, path: str, json: dict | None = None, params: dict | None = None):
        api_path = self._api_path(path)
        canonical = self._canonical(api_path, params)
        signature = self._sign(canonical)

        url = f"{self.base_url}{api_path}"
        r = requests.post(
            url,
            params={"apikey": self.apikey, **(params or {}), "signature": signature},
            json=json,
            timeout=self.timeout,
        )
        return r
