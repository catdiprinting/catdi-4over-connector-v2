import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

from config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
)

class FourOverClient:
    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("4over API keys missing")

    def _signature(self, path: str, params: dict):
        canonical = path
        if params:
            canonical += "?" + urlencode(sorted(params.items()))

        return hmac.new(
            FOUR_OVER_PRIVATE_KEY.encode(),
            canonical.encode(),
            hashlib.sha1
        ).hexdigest()

    def get(self, path: str, params: dict | None = None):
        params = params or {}
        params["apikey"] = FOUR_OVER_APIKEY
        params["timestamp"] = str(int(time.time()))

        sig = self._signature(path, {"apikey": params["apikey"]})

        params["signature"] = sig

        url = f"{FOUR_OVER_BASE_URL}{path}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

client = FourOverClient()
