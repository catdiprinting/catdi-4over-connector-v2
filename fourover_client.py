import os
import hashlib
import hmac
import requests
from urllib.parse import urlencode, urljoin


def normalize_private_key(pk: str) -> str:
    return (pk or "").strip()


def build_canonical_path_and_query(path: str, query: dict) -> str:
    items = sorted(
        (k, str(v))
        for k, v in (query or {}).items()
        if v is not None and k != "signature"
    )
    qs = urlencode(items)
    return f"{path}?{qs}" if qs else path


def sign_4over(method: str, canonical_path_and_query: str, private_key: str) -> str:
    pk = normalize_private_key(private_key)
    hmac_key = hashlib.sha256(pk.encode("utf-8")).hexdigest().encode("utf-8")
    msg = (method.upper() + canonical_path_and_query).encode("utf-8")
    return hmac.new(hmac_key, msg, hashlib.sha256).hexdigest()


class FourOverClient:
    def __init__(self):
        self.base_url = (os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com") or "").rstrip("/")
        self.apikey = os.getenv("FOUR_OVER_APIKEY", "") or ""
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "") or ""

        if not self.base_url or not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_BASE_URL / FOUR_OVER_APIKEY / FOUR_OVER_PRIVATE_KEY")

        self.session = requests.Session()
        self.timeout = (5, 25)

    def get(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["apikey"] = self.apikey

        canonical = build_canonical_path_and_query(path, params)
        sig = sign_4over("GET", canonical, self.private_key)
        params["signature"] = sig

        url = urljoin(self.base_url + "/", path.lstrip("/"))
        resp = self.session.get(url, params=params, timeout=self.timeout)
        return resp, {"url": url, "canonical": canonical, "signature": sig}
