import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

class FourOverClient:
    def __init__(self):
        self.base_url = os.getenv("FOUROVER_BASE_URL", "https://api.4over.com").rstrip("/")
        self.api_key = os.getenv("FOUROVER_API_KEY", "").strip()
        self.private_key = os.getenv("FOUROVER_PRIVATE_KEY", "").strip()

        if not self.api_key or not self.private_key:
            raise RuntimeError("Missing FOUROVER_API_KEY or FOUROVER_PRIVATE_KEY in env vars")

    def _signature(self, canonical: str) -> str:
        # canonical like "/printproducts?offset=0&perPage=20"
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _request(self, path: str, params: dict | None = None):
        params = params or {}
        canonical = path
        if params:
            canonical = f"{path}?{urlencode(params)}"

        sig = self._signature(canonical)
        url = f"{self.base_url}{canonical}"
        headers = {"Accept": "application/json"}

        # 4over style auth (apikey + signature)
        auth_params = {"apikey": self.api_key, "signature": sig}
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}{urlencode(auth_params)}"

        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()

    def whoami(self):
        return self._request("/whoami")

    def list_printproducts(self, offset: int = 0, perPage: int = 20):
        # Your tests showed perPage gets capped to 20
        return self._request("/printproducts", {"offset": offset, "perPage": perPage})

    def get_printproduct(self, item_id: str):
        return self._request(f"/printproducts/{item_id}")
