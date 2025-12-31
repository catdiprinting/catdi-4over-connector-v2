# fourover_client.py
import hashlib
import hmac
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


def _signature_for(method: str) -> str:
    """
    4over doc working mode for YOUR account:
      signature = hmac_sha256(HTTP_METHOD, sha256(private_key).hexdigest())
    i.e. key is the SHA256(private_key) rendered as a hex string, encoded as UTF-8 bytes.
    """
    method_bytes = method.upper().encode("utf-8")
    key = hashlib.sha256(FOUR_OVER_PRIVATE_KEY.encode("utf-8")).hexdigest().encode("utf-8")
    return hmac.new(key, method_bytes, hashlib.sha256).hexdigest()


def get(path: str, params: dict | None = None, timeout: int = 20) -> dict:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise FourOverError(0, "", "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY env vars", path)

    q = {"apikey": FOUR_OVER_APIKEY, **(params or {})}
    q["signature"] = _signature_for("GET")

    canonical = f"{path}?{urlencode(q)}"
    url = f"{FOUR_OVER_BASE_URL}{path}?{urlencode(q)}"

    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise FourOverError(r.status_code, url, r.text, canonical)
    return r.json()


def whoami() -> dict:
    return get("/whoami")


def product_baseprices(product_uuid: str) -> dict:
    return get(f"/printproducts/products/{product_uuid}/baseprices")
