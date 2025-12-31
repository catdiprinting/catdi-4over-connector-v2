# fourover_client.py
import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY


class FourOverError(RuntimeError):
    def __init__(self, status: int, url: str, body: str, canonical: str):
        super().__init__(f"4over request failed ({status})")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def _signature(canonical: str) -> str:
    """
    4over HMAC signature pattern we used in your working builds:
    signature = HMAC-SHA1(private_key, canonical).hexdigest()
    """
    key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha1).hexdigest()


def get(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise FourOverError(
            0,
            "",
            "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY env vars",
            path,
        )

    q = dict(params or {})
    q["apikey"] = FOUR_OVER_APIKEY
    q["timestamp"] = int(time.time())

    canonical = f"{path}?{urlencode(q)}"
    q["signature"] = _signature(canonical)

    url = f"{FOUR_OVER_BASE_URL}{path}?{urlencode(q)}"

    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise FourOverError(r.status_code, url, r.text, canonical)
    return r.json()


def whoami() -> dict:
    return get("/whoami")


def product_baseprices(product_uuid: str) -> dict:
    return get(f"/printproducts/products/{product_uuid}/baseprices")
