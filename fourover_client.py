import hashlib
import hmac
import requests
from urllib.parse import urlencode

from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY


class FourOverError(RuntimeError):
    def __init__(self, status: int, url: str, body: str, canonical: str):
        super().__init__(f"4over request failed ({status})")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def signature_for(method: str) -> str:
    """
    Docs:
      signature = HMAC_SHA256(HTTP_METHOD, sha256(private_key))
    """
    m = method.upper().encode("utf-8")
    key = hashlib.sha256(FOUR_OVER_PRIVATE_KEY.encode("utf-8")).hexdigest().encode("utf-8")
    return hmac.new(key, m, hashlib.sha256).hexdigest()


def get(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    """
    GET auth: apikey + signature (no timestamp) ✅ matches your working whoami calls.
    """
    params = params or {}
    q = {"apikey": FOUR_OVER_APIKEY, **params, "signature": signature_for("GET")}
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
