# fourover_client.py
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
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


def _clean(s: str | None) -> str:
    return (s or "").strip()


def _base_url() -> str:
    return _clean(FOUR_OVER_BASE_URL).rstrip("/")


def _sorted_query(params: dict[str, Any]) -> str:
    items = sorted(params.items(), key=lambda kv: kv[0])
    return urlencode(items, doseq=True)


def _signature_sha256(canonical: str) -> str:
    key = _clean(FOUR_OVER_PRIVATE_KEY).encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


@dataclass
class SignedRequest:
    url: str
    canonical: str
    signature: str


def build_signed_url(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    use_timestamp: bool = False,  # IMPORTANT: default OFF to match your working style
) -> SignedRequest:
    apikey = _clean(FOUR_OVER_APIKEY)
    pkey = _clean(FOUR_OVER_PRIVATE_KEY)
    if not apikey or not pkey:
        raise FourOverError(0, "", "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY", path)

    q: dict[str, Any] = dict(params or {})
    q["apikey"] = apikey

    if use_timestamp and "timestamp" not in q:
        q["timestamp"] = int(time.time())

    canonical = f"{path}?{_sorted_query(q)}"
    signature = _signature_sha256(canonical)

    q2 = dict(q)
    q2["signature"] = signature

    url = f"{_base_url()}{path}?{_sorted_query(q2)}"
    return SignedRequest(url=url, canonical=canonical, signature=signature)


def get(path: str, params: dict[str, Any] | None = None, timeout: int = 30, *, use_timestamp: bool = False) -> dict:
    signed = build_signed_url(path, params, use_timestamp=use_timestamp)
    r = requests.get(signed.url, timeout=timeout)

    if r.status_code >= 400:
        raise FourOverError(r.status_code, signed.url, r.text, signed.canonical)

    return r.json()


def whoami() -> dict:
    # timestamp OFF to match your proven-working canonical style
    return get("/whoami", use_timestamp=False)


def product_baseprices(product_uuid: str) -> dict:
    # timestamp OFF to match your proven-working canonical style
    return get(f"/printproducts/products/{product_uuid}/baseprices", use_timestamp=False)
