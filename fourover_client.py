# fourover_client.py
import os
import hmac
import hashlib
import requests
from typing import Any, Dict, Optional
from urllib.parse import urlencode

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")


class FourOverError(Exception):
    def __init__(self, status: int, url: str, body: str, canonical: str):
        super().__init__(f"4over error {status}")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def _signature(canonical: str) -> str:
    # 4over signature is HMAC-SHA256 over canonical path+query using PRIVATE_KEY
    key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 25) -> Dict[str, Any]:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise FourOverError(
            status=401,
            url="",
            body="Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY",
            canonical="",
        )

    params = params or {}
    params["apikey"] = FOUR_OVER_APIKEY

    query = urlencode(params, doseq=True)
    canonical = f"{path}?{query}" if query else path
    sig = _signature(canonical)

    url = f"{FOUR_OVER_BASE_URL}{canonical}&signature={sig}" if query else f"{FOUR_OVER_BASE_URL}{canonical}?signature={sig}"

    r = requests.get(url, timeout=timeout)
    if r.status_code >= 400:
        raise FourOverError(status=r.status_code, url=url, body=r.text, canonical=canonical)

    return r.json()


def whoami() -> Dict[str, Any]:
    return _get("/whoami")


def product_baseprices(product_uuid: str) -> Dict[str, Any]:
    return _get(f"/printproducts/products/{product_uuid}/baseprices")


def product_optiongroups(product_uuid: str) -> Dict[str, Any]:
    # This returns the structure that includes option groups for size/stock/coating/turnaround, etc.
    return _get(f"/printproducts/products/{product_uuid}/optiongroups")
