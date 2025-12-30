import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


class FourOverClient:
    def __init__(self):
        self.base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        self.apikey = os.getenv("FOUR_OVER_APIKEY", "")
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

    def _sign(self, canonical: str) -> str:
        return hmac.new(self.private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _build_url(self, path: str, params: dict | None = None) -> str:
        path = "/" + path.lstrip("/")
        params = params or {}

        # 4over signature pattern: signature over "path?sorted_query_without_signature"
        # Always include apikey in query
        params["apikey"] = self.apikey

        # Build canonical query string (sorted)
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        query = urlencode(sorted_items)

        canonical = f"{path}?{query}"
        signature = self._sign(canonical)

        # Add signature and timestamp
        # (Some 4over setups accept timestamp; you already have whoami working, keep consistent)
        ts = str(int(time.time()))
        full_query = f"{query}&signature={signature}&timestamp={ts}"
        return f"{self.base_url}{path}?{full_query}"

    def get(self, path: str, params: dict | None = None, timeout: int = 30):
        url = self._build_url(path, params=params)
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
