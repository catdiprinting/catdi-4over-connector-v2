# fourover_client.py
import os
import hmac
import hashlib
from urllib.parse import urlencode
import requests

class FourOverError(Exception):
    def __init__(self, status: int, url: str, body: str, canonical: str):
        super().__init__(f"4over error {status}")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical

def _env_required(name: str) -> str:
    v = os.getenv(name)
    if v is None:
        raise RuntimeError(f"Missing required env var: {name}")
    v = v.strip()
    if not v:
        raise RuntimeError(f"Empty required env var: {name}")
    return v

def _base_url() -> str:
    return os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").strip() or "https://api.4over.com"

def _sign(path: str, apikey: str, private_key: str, extra_params: dict | None = None) -> tuple[str, str]:
    params = {"apikey": apikey}
    if extra_params:
        for k in sorted(extra_params.keys()):
            params[k] = extra_params[k]
    query = urlencode(params)
    canonical = f"{path}?{query}"
    sig = hmac.new(private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return canonical, sig

def _get_json(path: str, extra_params: dict | None = None) -> dict:
    apikey = _env_required("FOUR_OVER_APIKEY")
    private_key = _env_required("FOUR_OVER_PRIVATE_KEY")
    base = _base_url()

    canonical, sig = _sign(path, apikey, private_key, extra_params=extra_params)
    url = f"{base}{canonical}&signature={sig}"

    r = requests.get(url, timeout=30)
    if r.status_code >= 400:
        raise FourOverError(r.status_code, url, r.text, canonical)
    return r.json()

def whoami() -> dict:
    return _get_json("/whoami")

def product_baseprices(product_uuid: str) -> dict:
    return _get_json(f"/printproducts/products/{product_uuid}/baseprices")

def product_optiongroups(product_uuid: str) -> dict:
    return _get_json(f"/printproducts/products/{product_uuid}/optiongroups")
