import os
import time
import hmac
import hashlib
import requests
from dataclasses import dataclass
from urllib.parse import urlencode


class FourOverError(Exception):
    def __init__(self, status: int, url: str, body: str = "", canonical: str = ""):
        super().__init__(f"4over request failed status={status} url={url}")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _base_url() -> str:
    return os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")


def _apikey() -> str:
    return _env("FOUR_OVER_APIKEY")


def _private_key() -> str:
    return _env("FOUR_OVER_PRIVATE_KEY")


def _signature_for_canonical(canonical: str) -> str:
    # 4over expects HMAC-SHA256 over canonical path+query
    key = _private_key().encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _signed_url(path: str, params: dict | None = None) -> tuple[str, str]:
    """
    Returns (url, canonical) where canonical is '/path?apikey=...&x=y'
    """
    params = dict(params or {})
    params["apikey"] = _apikey()

    # stable ordering of query params
    query = urlencode(sorted(params.items()), doseq=True)
    canonical = f"{path}?{query}"

    sig = _signature_for_canonical(canonical)
    url = f"{_base_url()}{canonical}&signature={sig}"
    return url, canonical


@dataclass
class FourOverClient:
    timeout: int = 30

    def get(self, path: str, params: dict | None = None) -> dict:
        url, canonical = _signed_url(path, params=params)
        try:
            r = requests.get(url, timeout=self.timeout)
        except Exception as e:
            raise FourOverError(status=502, url=url, body=str(e), canonical=canonical)

        if r.status_code >= 400:
            raise FourOverError(status=r.status_code, url=url, body=r.text, canonical=canonical)

        try:
            return r.json()
        except Exception:
            raise FourOverError(status=502, url=url, body=r.text, canonical=canonical)


# ✅ This is what your router expects:
client = FourOverClient(timeout=30)


# ---- Friendly wrappers your main.py already uses ----

def whoami() -> dict:
    return client.get("/whoami")


def product_baseprices(product_uuid: str) -> dict:
    return client.get(f"/printproducts/products/{product_uuid}/baseprices")


def product_optiongroups(product_uuid: str) -> dict:
    return client.get(f"/printproducts/products/{product_uuid}/optiongroups")
