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


def _signature_for(method: str, *, key_mode: str = "hexdigest") -> str:
    """
    4over doc (GET/DELETE):
      signature = hmac_sha256(HTTP_METHOD, sha256(private_key))

    key_mode variants:
      - "hexdigest" (matches the doc example literally)
      - "digest" (sometimes APIs expect raw bytes)
      - "hexbytes" (bytes.fromhex of hexdigest)
    """
    method_bytes = method.upper().encode("utf-8")

    sha = hashlib.sha256(FOUR_OVER_PRIVATE_KEY.encode("utf-8"))
    if key_mode == "hexdigest":
        key = sha.hexdigest().encode("utf-8")
    elif key_mode == "digest":
        key = sha.digest()
    elif key_mode == "hexbytes":
        key = bytes.fromhex(sha.hexdigest())
    else:
        raise ValueError("Invalid key_mode")

    return hmac.new(key, method_bytes, hashlib.sha256).hexdigest()


def get(path: str, params: dict | None = None, timeout: int = 20, *, key_mode: str = "hexdigest") -> dict:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise FourOverError(
            0,
            "",
            "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY env vars",
            path,
        )

    params = params or {}
    q = {"apikey": FOUR_OVER_APIKEY, **params, "signature": _signature_for("GET", key_mode=key_mode)}
    canonical = f"{path}?{urlencode(q)}"
    url = f"{FOUR_OVER_BASE_URL}{path}?{urlencode(q)}"

    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise FourOverError(r.status_code, url, r.text, canonical)
    return r.json()


def whoami(*, key_mode: str = "hexdigest") -> dict:
    return get("/whoami", key_mode=key_mode)


def product_baseprices(product_uuid: str, *, key_mode: str = "hexdigest") -> dict:
    return get(f"/printproducts/products/{product_uuid}/baseprices", key_mode=key_mode)
