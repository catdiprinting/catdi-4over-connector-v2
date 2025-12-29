import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


class FourOverClient:
    def __init__(self, base_url: str = "https://api.4over.com"):
        # Accept multiple env var names to avoid Railway mismatch
        self.api_key = (
            os.getenv("FOUROVER_API_KEY")
            or os.getenv("FOUROVER_APIKEY")
            or os.getenv("FOUROVER_KEY")
            or os.getenv("FOUROVER_PUBLIC_KEY")
            or os.getenv("FOUROVER_APIUSERNAME")
        )

        self.private_key = (
            os.getenv("FOUROVER_PRIVATE_KEY")
            or os.getenv("FOUROVER_SECRET_KEY")
            or os.getenv("FOUROVER_SECRET")
            or os.getenv("FOUROVER_PRIVATE")
        )

        if not self.api_key or not self.private_key:
            raise RuntimeError("Missing FOUROVER_API_KEY or FOUROVER_PRIVATE_KEY in env vars")

        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _sign(self, canonical: str) -> str:
        # 4over expects HMAC SHA256 hex digest
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method: str, path: str, params: dict | None = None):
        params = params or {}
        # IMPORTANT: signature is calculated on canonical path + query (apikey included)
        params_with_key = dict(params)
        params_with_key["apikey"] = self.api_key

        query = urlencode(sorted(params_with_key.items()))
        canonical = f"{path}?{query}" if query else path
        signature = self._sign(canonical)

        url = f"{self.base_url}{path}"
        final_params = dict(params_with_key)
        final_params["signature"] = signature

        resp = self.session.request(method, url, params=final_params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # ---- Adjust this endpoint path if your catalog endpoint differs ----
    def get_catalog(self, offset: int = 0, per_page: int = 200):
        # If API caps page size to 20, that's OK — your paging loop handles it.
        return self._request(
            "GET",
            "/printproducts",
            params={"offset": offset, "perPage": per_page},
        )
