# app/fourover_client.py
import hmac
import hashlib
import os
from urllib.parse import urlencode
import requests


class FourOverClient:
    """
    4over auth (working approach):
      - query always includes apikey
      - signature = HMAC-SHA256(private_key, canonical_string)
      - canonical_string = <path>?<sorted querystring>
      - DO NOT add timestamps unless the docs explicitly require them.
    """

    def __init__(self):
        self.base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        self.api_prefix = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")

        self.apikey = os.getenv("FOUR_OVER_APIKEY", "")
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

        timeout = os.getenv("FOUR_OVER_TIMEOUT", "30")
        try:
            self.timeout = int(timeout)
        except Exception:
            self.timeout = 30

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY in env")

    def _normalize_path(self, path: str) -> str:
        """
        Ensures we call:
          https://api.4over.com/<api_prefix>/<path_without_prefix>
        """
        if not path.startswith("/"):
            path = "/" + path

        # Strip prefix if caller already included it (prevents /printproducts/printproducts/...)
        pref = f"/{self.api_prefix}"
        if path.startswith(pref + "/"):
            path = path[len(pref):]  # remove leading /printproducts

        # Final API path always includes prefix once
        return f"/{self.api_prefix}{path}"

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def get(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["apikey"] = self.apikey

        api_path = self._normalize_path(path)

        # IMPORTANT: stable ordering for signature
        qs = urlencode(sorted(params.items()), doseq=True)

        canonical = f"{api_path}?{qs}"
        signature = self._sign(canonical)

        url = f"{self.base_url}{api_path}?{qs}&signature={signature}"

        resp = requests.get(url, timeout=self.timeout)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}

    def post(self, path: str, json_body: dict | None = None, params: dict | None = None):
        params = dict(params or {})
        params["apikey"] = self.apikey

        api_path = self._normalize_path(path)
        qs = urlencode(sorted(params.items()), doseq=True)
        canonical = f"{api_path}?{qs}"
        signature = self._sign(canonical)

        url = f"{self.base_url}{api_path}?{qs}&signature={signature}"

        resp = requests.post(url, json=json_body or {}, timeout=self.timeout)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}
