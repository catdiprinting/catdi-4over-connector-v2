# fourover_client.py
import os
import hashlib
import hmac
import requests
from urllib.parse import urlencode


class FourOverClient:
    """
    Docs-based auth (reverted to API docs):
      signature = HMAC_SHA256(key=SHA256(private_key), msg=HTTP_METHOD)
    For GET/DELETE: pass apikey + signature in querystring. :contentReference[oaicite:2]{index=2}:contentReference[oaicite:3]{index=3}
    """

    def __init__(self):
        self.base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        self.public_key = os.getenv("FOUR_OVER_APIKEY", "").strip()
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "").strip()

        if not self.public_key or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY and/or FOUR_OVER_PRIVATE_KEY env vars")

        self._hashed_private = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _signature_for_method(self, method: str) -> str:
        msg = method.upper().encode("utf-8")
        key = self._hashed_private.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def get(self, path: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
        params = dict(params or {})
        params["apikey"] = self.public_key
        params["signature"] = self._signature_for_method("GET")

        url = f"{self.base_url}{path}"
        return self.session.get(url, params=params, timeout=timeout)

    def debug_get_url(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["apikey"] = self.public_key
        params["signature"] = self._signature_for_method("GET")
        return {
            "base_url": self.base_url,
            "path": path,
            "query": params,
            "full_url": f"{self.base_url}{path}?{urlencode(params)}",
        }
