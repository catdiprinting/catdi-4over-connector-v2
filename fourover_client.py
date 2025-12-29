import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

class FourOverClient:
    """
    4over signing notes (based on your previously-working behavior):
    - key_for_hmac = sha256(private_key)  (hex digest bytes)
    - signature = HMAC-SHA256(key_for_hmac, canonical_string)
    - canonical_string = path + '?' + sorted_querystring (must include apikey; exclude signature)
    """

    def __init__(self):
        # Accept either env naming style
        self.api_key = (
            os.getenv("FOUROVER_API_KEY")
            or os.getenv("FOUR_OVER_APIKEY")
            or os.getenv("FOUR_OVER_API_KEY")
            or ""
        ).strip()

        self.private_key = (
            os.getenv("FOUROVER_PRIVATE_KEY")
            or os.getenv("FOUR_OVER_PRIVATE_KEY")
            or ""
        ).strip()

        self.base_url = (
            os.getenv("FOUROVER_BASE_URL")
            or os.getenv("FOUR_OVER_BASE_URL")
            or "https://api.4over.com"
        ).strip().rstrip("/")

        if not self.api_key or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY/FOUR_OVER_PRIVATE_KEY (or FOUROVER_*) in env vars")

        self.session = requests.Session()

        # HMAC key is sha256(private_key) (HEX digest bytes)
        sha = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()
        self.hmac_key = sha.encode("utf-8")

    def _canonical(self, path: str, params: dict) -> str:
        # Remove signature from canonical inputs if present
        cleaned = {k: v for k, v in params.items() if k != "signature" and v is not None}

        # Sort params by key (string)
        sorted_items = sorted((str(k), str(v)) for k, v in cleaned.items())

        qs = urlencode(sorted_items)
        return f"{path}?{qs}" if qs else path

    def _sign(self, canonical: str) -> str:
        return hmac.new(self.hmac_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def request(self, method: str, path: str, params: dict | None = None, timeout: int = 30):
        params = dict(params or {})

        # Ensure apikey is always included
        params["apikey"] = self.api_key

        canonical = self._canonical(path, params)
        signature = self._sign(canonical)
        params["signature"] = signature

        url = f"{self.base_url}{path}"

        # retries with backoff (helps Railway + 4over occasional blips)
        last_exc = None
        for attempt in range(1, 5):
            try:
                resp = self.session.request(method.upper(), url, params=params, timeout=timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    # retry on transient errors
                    time.sleep(0.6 * attempt)
                    continue
                resp.raise_for_status()
                # 4over commonly returns JSON
                ct = resp.headers.get("content-type", "")
                if "application/json" in ct:
                    return resp.json()
                return {"raw": resp.text}
            except Exception as e:
                last_exc = e
                time.sleep(0.6 * attempt)

        raise last_exc  # type: ignore

    # Convenience methods
    def whoami(self):
        return self.request("GET", "/whoami")

    def explore_path(self, path: str, offset: int = 0, per_page: int = 20):
        # Many 4over endpoints respect offset/perPage; you confirmed enforced 20.
        return self.request("GET", path, params={"offset": offset, "perPage": per_page})
