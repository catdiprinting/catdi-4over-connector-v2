from __future__ import annotations

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


def _require_keys() -> None:
    if not FOUR_OVER_BASE_URL:
        raise RuntimeError("FOUR_OVER_BASE_URL is missing")
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")
    if not FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing")


def _canonical_query(params: dict) -> str:
    # Stable ordering matters for signature reproducibility
    items = sorted((k, str(v)) for k, v in params.items() if v is not None)
    return urlencode(items)


def signature_for_canonical(canonical: str) -> str:
    """
    Canonical signing approach:
      signature = HMAC_SHA256(canonical, private_key)
    (canonical includes path + querystring WITHOUT signature param)
    """
    key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class FourOverClient:
    def __init__(self, base_url: str = FOUR_OVER_BASE_URL):
        _require_keys()
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, params: dict | None = None, timeout: int = 30) -> dict:
        params = params or {}
        # Build canonical params excluding signature
        q = {"apikey": FOUR_OVER_APIKEY, **params}
        canonical = f"{path}?{_canonical_query(q)}"
        sig = signature_for_canonical(canonical)

        # Final URL includes signature
        q_with_sig = {**q, "signature": sig}
        url = f"{self.base_url}{path}?{_canonical_query(q_with_sig)}"

        r = requests.request(method.upper(), url, timeout=timeout)
        if r.status_code >= 400:
            raise FourOverError(r.status_code, url, r.text, canonical)

        # Some endpoints can return non-json; guard it
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    def whoami(self) -> dict:
        return self.request("GET", "/whoami")

    def product_baseprices(self, product_uuid: str) -> dict:
        return self.request("GET", f"/printproducts/products/{product_uuid}/baseprices")

    def product_optiongroups(self, product_uuid: str) -> dict:
        return self.request("GET", f"/printproducts/products/{product_uuid}/optiongroups")
