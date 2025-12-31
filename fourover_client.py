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


def _normalized_base_url() -> str:
    # Prevent double slashes and subtle signature/url mismatches
    return _clean(FOUR_OVER_BASE_URL).rstrip("/")


def _sorted_query(params: dict[str, Any]) -> str:
    """
    Deterministic query order is CRITICAL for stable signatures.
    urlencode() preserves order of the input sequence, so we sort.
    """
    items = sorted(params.items(), key=lambda kv: kv[0])
    return urlencode(items, doseq=True)


def _signature_sha256(canonical: str) -> str:
    """
    HMAC-SHA256 hex digest signature.
    """
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
    use_timestamp: bool = True,
) -> SignedRequest:
    """
    Builds (url, canonical, signature) in a deterministic way.

    canonical = "{path}?{sorted_query_without_signature}"
    url       = "{base}{path}?{sorted_query_with_signature}"
    """
    apikey = _clean(FOUR_OVER_APIKEY)
    pkey = _clean(FOUR_OVER_PRIVATE_KEY)
    if not apikey or not pkey:
        raise FourOverError(0, "", "Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY", path)

    q: dict[str, Any] = dict(params or {})
    q["apikey"] = apikey

    if use_timestamp and "timestamp" not in q:
        # 4over commonly supports/uses timestamp signing; keep it stable.
        q["timestamp"] = int(time.time())

    # canonical excludes signature
    canonical = f"{path}?{_sorted_query(q)}"
    signature = _signature_sha256(canonical)

    q_with_sig = dict(q)
    q_with_sig["signature"] = signature

    base = _normalized_base_url()
    url = f"{base}{path}?{_sorted_query(q_with_sig)}"
    return SignedRequest(url=url, canonical=canonical, signature=signature)


def get(path: str, params: dict[str, Any] | None = None, timeout: int = 30, *, use_timestamp: bool = True) -> dict:
    signed = build_signed_url(path, params, use_timestamp=use_timestamp)
    r = requests.get(signed.url, timeout=timeout)

    if r.status_code >= 400:
        raise FourOverError(r.status_code, signed.url, r.text, signed.canonical)

    return r.json()


def whoami() -> dict:
    # keep timestamp ON for stability across endpoints
    return get("/whoami", use_timestamp=True)


def product_baseprices(product_uuid: str) -> dict:
    return get(f"/printproducts/products/{product_uuid}/baseprices", use_timestamp=True)
