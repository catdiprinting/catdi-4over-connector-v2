# fourover_client.py
import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class FourOverClient:
    """
    Minimal 4over client using API key + private key signature.
    We build URLs as:
      {base}{path}?apikey=...&signature=...&{other query params}

    Signature is HMAC-SHA256(private_key, canonical_string)
    canonical_string = f"{path}?apikey={apikey}"   (then append any other query params in sorted order)
    """

    def __init__(self, api_key: str, private_key: str, base_url: str = "https://api.4over.com"):
        if not api_key or not private_key:
            raise ValueError("FOUROVER_API_KEY and FOUROVER_PRIVATE_KEY are required.")
        self.api_key = api_key
        self.private_key = private_key.encode("utf-8")
        self.base_url = base_url.rstrip("/")

    def _canonical(self, path: str, params: dict) -> str:
        # apikey must be included in canonical
        merged = {"apikey": self.api_key, **(params or {})}
        # Sort params for stable canonical string
        items = sorted((k, str(v)) for k, v in merged.items() if v is not None)
        qs = urlencode(items)
        return f"{path}?{qs}"

    def _sign(self, canonical: str) -> str:
        return hmac.new(self.private_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def build_url(self, path: str, params: dict | None = None) -> str:
        if not path.startswith("/"):
            path = "/" + path

        canonical = self._canonical(path, params or {})
        signature = self._sign(canonical)

        # Final params include signature
        merged = {"apikey": self.api_key, **(params or {}), "signature": signature}
        items = sorted((k, str(v)) for k, v in merged.items() if v is not None)
        qs = urlencode(items)
        return f"{self.base_url}{path}?{qs}"

    def get(self, path: str, params: dict | None = None, timeout: int = 60):
        url = self.build_url(path, params=params)
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()

    # Convenience endpoints
    def whoami(self):
        return self.get("/whoami")

    def products(self, q: str | None = None, limit: int = 50, offset: int = 0):
        params = {"limit": limit, "offset": offset}
        if q:
            params["q"] = q
        return self.get("/products", params=params)
