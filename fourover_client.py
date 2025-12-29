import os
import hmac
import hashlib
import requests
from urllib.parse import urlencode


def _first_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return None


class FourOverClient:
    def __init__(self, base_url: str | None = None):
        # ✅ Support Railway variable naming: FOUR_OVER_*
        self.api_key = _first_env(
            "FOUR_OVER_APIKEY",
            "FOUR_OVER_API_KEY",
            "FOUROVER_API_KEY",
            "FOUROVER_APIKEY",
            "FOUROVER_KEY",
            "APIKEY",
        )

        self.private_key = _first_env(
            "FOUR_OVER_PRIVATE_KEY",
            "FOUR_OVER_SECRET_KEY",
            "FOUROVER_PRIVATE_KEY",
            "FOUROVER_SECRET_KEY",
            "FOUROVER_SECRET",
            "PRIVATEKEY",
            "SECRET",
        )

        env_base = _first_env(
            "FOUR_OVER_BASE_URL",
            "FOUROVER_BASE_URL",
        )

        self.base_url = (base_url or env_base or "https://api.4over.com").strip().rstrip("/")

        if not self.api_key or not self.private_key:
            present = {k: bool(os.getenv(k)) for k in [
                "FOUR_OVER_APIKEY", "FOUR_OVER_API_KEY", "FOUR_OVER_PRIVATE_KEY", "FOUR_OVER_SECRET_KEY", "FOUR_OVER_BASE_URL",
                "FOUROVER_API_KEY", "FOUROVER_PRIVATE_KEY", "FOUROVER_BASE_URL",
            ]}
            raise RuntimeError(
                "Missing 4over env vars. In Railway Variables set FOUR_OVER_APIKEY and FOUR_OVER_PRIVATE_KEY "
                f"(optional FOUR_OVER_BASE_URL). Present flags: {present}"
            )

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(self, method: str, path: str, params: dict | None = None):
        params = params or {}

        params_with_key = dict(params)
        params_with_key["apikey"] = self.api_key

        # Sort params before signing to keep canonical stable
        query = urlencode(sorted(params_with_key.items()))
        canonical = f"{path}?{query}" if query else path
        signature = self._sign(canonical)

        url = f"{self.base_url}{path}"
        final_params = dict(params_with_key)
        final_params["signature"] = signature

        resp = self.session.request(method, url, params=final_params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def get_printproducts(self, offset: int = 0, per_page: int = 200):
        return self._request(
            "GET",
            "/printproducts",
            params={"offset": offset, "perPage": per_page},
        )
