# four_over_client.py
import os
import hmac
import hashlib
import requests
from urllib.parse import urlencode

DEFAULT_BASE = "https://api.4over.com"


class FourOverClient:
    def __init__(self, api_key: str, private_key: str, base_url: str = DEFAULT_BASE, timeout: int = 60):
        self.api_key = api_key
        self.private_key = private_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _signature(self, canonical: str) -> str:
        # HMAC-SHA256(private_key, canonical) hex digest
        return hmac.new(self.private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def request(self, method: str, path: str, params: dict | None = None):
        params = params or {}

        # 4over signature uses canonical path + query WITHOUT signature itself
        canonical_query = urlencode(sorted(params.items()))
        canonical = f"{path}?{canonical_query}" if canonical_query else path

        sig = self._signature(canonical)

        # add auth params
        final_params = dict(params)
        final_params["apikey"] = self.api_key
        final_params["signature"] = sig

        url = f"{self.base_url}{path}"

        resp = requests.request(method.upper(), url, params=final_params, timeout=self.timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {"http_status": resp.status_code, "ok": resp.ok, "data": data}
        

def get_client_from_env() -> FourOverClient:
    api_key = os.getenv("FOUROVER_APIKEY", "")
    private_key = os.getenv("FOUROVER_PRIVATE_KEY", "")
    if not api_key or not private_key:
        raise RuntimeError("Missing env vars: FOUROVER_APIKEY and/or FOUROVER_PRIVATE_KEY")
    return FourOverClient(api_key=api_key, private_key=private_key)
