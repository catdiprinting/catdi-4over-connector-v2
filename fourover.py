# fourover.py
import hashlib
import hmac
import time
import requests
from urllib.parse import urlencode

from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY


class FourOverClient:
    def __init__(self, base_url: str = FOUR_OVER_BASE_URL, apikey: str = FOUR_OVER_APIKEY, private_key: str = FOUR_OVER_PRIVATE_KEY):
        self.base_url = (base_url or "").rstrip("/")
        self.apikey = apikey or ""
        self.private_key = private_key or ""

        if not self.base_url:
            raise ValueError("FOUR_OVER_BASE_URL is missing")
        if not self.apikey:
            raise ValueError("FOUR_OVER_APIKEY is missing")
        if not self.private_key:
            raise ValueError("FOUR_OVER_PRIVATE_KEY is missing")

    def _sign(self, canonical: str) -> str:
        # 4over expects HMAC SHA256 signature of the canonical path+query string
        # canonical example: "/whoami?apikey=XXXXX"
        digest = hmac.new(self.private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return digest

    def request(self, method: str, path: str, params: dict | None = None, json: dict | None = None, timeout: int = 30):
        method = method.upper()
        params = params.copy() if params else {}

        # Ensure apikey is always present
        params["apikey"] = self.apikey

        # Build canonical string for signing (path + ?query)
        query = urlencode(params)
        canonical = f"{path}?{query}" if query else path

        signature = self._sign(canonical)

        # 4over uses signature as query param
        params["signature"] = signature

        url = f"{self.base_url}{path}"

        r = requests.request(method, url, params=params, json=json, timeout=timeout)
        return r

    def whoami(self):
        return self.request("GET", "/whoami")

    def categories(self):
        return self.request("GET", "/printproducts/categories")

    def category_products(self, category_uuid: str, page: int = 1):
        return self.request("GET", f"/printproducts/categories/{category_uuid}/products", params={"page": page})

    def product_options(self, product_uuid: str):
        return self.request("GET", f"/printproducts/products/{product_uuid}/options")

    def product_prices(self, product_uuid: str):
        return self.request("GET", f"/printproducts/products/{product_uuid}/prices")
