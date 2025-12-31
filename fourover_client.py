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


def _signature_sha256(canonical: str) -> str:
    """
    IMPORTANT:
    - This matches the previously working style you showed:
      canonical example: /whoami?apikey=catdi
      signature: sha256 HMAC hex (64 chars)
    - NO timestamp param (your working calls did not include it)
    """
    if not FOUR_OVER_PRIVATE_KEY:
        return ""
    key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def build_signed_url(path: str, params: dict | None = None) -> dict:
    """
    Returns {canonical, url, signature} for debugging.
    Canonical excludes signature, includes apikey and any other params.
    Uses stable param ordering (sorted keys) to avoid signature drift.
    """
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise FourOverError(
            0,
            "",
            "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY env vars",
            path,
        )

    q = dict(params or {})
    q["apikey"] = FOUR_OVER_APIKEY

    # Stable ordering to prevent regressions due to dict ordering differences
    ordered = [(k, q[k]) for k in sorted(q.keys())]
    canonical = f"{path}?{urlencode(ordered)}"

    signature = _signature_sha256(canonical)

    ordered_with_sig = ordered + [("signature", signature)]
    url = f"{FOUR_OVER_BASE_URL}{path}?{urlencode(ordered_with_sig)}"

    return {"canonical": canonical, "url": url, "signature": signature}


def get(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    debug = build_signed_url(path, params=params)
    url = debug["url"]
    canonical = debug["canonical"]

    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise FourOverError(r.status_code, url, r.text, canonical)

    return r.json()


def whoami() -> dict:
    return get("/whoami")


def product_baseprices(product_uuid: str) -> dict:
    return get(f"/printproducts/products/{product_uuid}/baseprices")
