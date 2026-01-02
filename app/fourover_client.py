import hashlib
import hmac
import os
from urllib.parse import urlencode
import requests


class FourOverClient:
    """Minimal 4over REST client.

    Key points (based on what has worked in your curl/debug output):
    - Signature = HMAC-SHA256 over canonical string: <path>?<sorted_query>
    - Query MUST include apikey
    - Do NOT add extra params (like timestamp) unless 4over docs explicitly require it.
    """

    def __init__(self):
        self.apikey = os.getenv("FOUR_OVER_APIKEY")
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY")
        self.base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        # Optional. Only used if caller passes non-prefixed paths.
        self.api_prefix = os.getenv("FOUR_OVER_API_PREFIX", "").strip("/")
        self.timeout = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        # Private key is used as raw bytes.
        self._key_bytes = self.private_key.encode("utf-8")

    def _normalize_path(self, path: str) -> str:
        """Ensure path starts with '/' and avoid duplicating api_prefix."""
        if not path.startswith("/"):
            path = "/" + path

        # If path already begins with /<prefix>/..., do not add prefix again.
        if self.api_prefix:
            pref = f"/{self.api_prefix}"
            if not path.startswith(pref + "/") and path != pref:
                # Only prefix routes that are not already prefixed.
                path = pref + path

        return path

    def _sign(self, canonical: str) -> str:
        return hmac.new(self._key_bytes, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def request(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["apikey"] = self.apikey

        # 4over signatures are sensitive to param ordering.
        # Sort by key for stable canonical + URL.
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        query = urlencode(sorted_items)

        norm_path = self._normalize_path(path)
        canonical = f"{norm_path}?{query}"
        signature = self._sign(canonical)

        # IMPORTANT: signature is appended to request query, but NOT included in canonical
        full_url = f"{self.base_url}{norm_path}?{query}&signature={signature}"

        resp = requests.get(full_url, timeout=self.timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {
            "ok": resp.ok,
            "http_code": resp.status_code,
            "url": full_url,
            "data": data,
            "debug": {
                "base": self.base_url,
                "path": norm_path,
                "canonical": canonical,
                "signature": signature,
            },
        }
