import os
import hmac
import hashlib
import requests
from urllib.parse import urlencode


class FourOverClient:
    """
    Minimal 4over API client using apikey + signature auth.
    Signature = HMAC-SHA256(private_key, canonical_path_with_query)
    """

    def __init__(self, apikey: str, private_key: str, base_url: str = "https://api.4over.com", timeout: int = 60):
        self.apikey = apikey
        self.private_key = private_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _sign(self, canonical: str) -> str:
        mac = hmac.new(self.private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256)
        return mac.hexdigest()

    def request(self, method: str, path: str, params: dict | None = None) -> dict:
        """
        path must start with /, e.g. /printproducts/productsfeed
        params are query params for the endpoint (offset, perPage, etc.)
        """
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")

        params = params or {}

        # canonical query WITHOUT apikey/signature first
        qs = urlencode(params, doseq=True)
        canonical = f"{path}?{qs}" if qs else path

        signature = self._sign(canonical)

        # actual query includes apikey + signature
        full_params = dict(params)
        full_params["apikey"] = self.apikey
        full_params["signature"] = signature

        url = f"{self.base_url}{path}"
        resp = requests.request(method.upper(), url, params=full_params, timeout=self.timeout)

        # 4over often returns JSON even on errors
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        if resp.status_code >= 400:
            raise RuntimeError(f"4over API error {resp.status_code}: {data}")

        return data

    def get_productsfeed(self, offset: int = 0, per_page: int = 200) -> dict:
        # NOTE: server may cap perPage; we detect the real count from returned items length.
        return self.request("GET", "/printproducts/productsfeed", params={"offset": offset, "perPage": per_page})


def get_client_from_env() -> FourOverClient:
    """
    Standard factory used by the app.
    Supports either env var naming.
    """
    api_key = os.getenv("FOUROVER_APIKEY") or os.getenv("FOUR_OVER_APIKEY")
    private_key = os.getenv("FOUROVER_PRIVATE_KEY") or os.getenv("FOUR_OVER_PRIVATE_KEY")
    base_url = os.getenv("FOUROVER_BASE_URL", "https://api.4over.com")

    if not api_key or not private_key:
        raise RuntimeError("Missing env vars: FOUROVER_APIKEY and FOUROVER_PRIVATE_KEY (or FOUR_OVER_*)")

    return FourOverClient(apikey=api_key, private_key=private_key, base_url=base_url)
