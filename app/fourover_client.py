# app/fourover_client.py
import hmac
import hashlib
from urllib.parse import urlencode
import requests


class FourOverClient:
    """
    4over auth pattern you were using:
      - GET uses query auth: ?apikey=XXX&signature=YYY
      - Signature is HMAC-SHA256(private_key, canonical_string)
      - canonical_string example: "/whoami?apikey=catdi"
    """

    def __init__(self, base_url: str, apikey: str, private_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.apikey = apikey
        self.private_key = private_key
        self.timeout = timeout

    def _canonical(self, path: str, params: dict | None = None) -> str:
        if not params:
            return path
        items = sorted((k, str(v)) for k, v in params.items() if v is not None)
        return f"{path}?{urlencode(items)}"

    def _sign(self, canonical: str) -> str:
        digest = hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["apikey"] = self.apikey

        canonical = self._canonical(path if path.startswith("/") else f"/{path}", params)
        sig = self._sign(canonical)
        params["signature"] = sig

        url = self._url(path)
        r = requests.get(url, params=params, timeout=self.timeout)
        try:
            return r.json()
        except Exception:
            return {"status": "error", "http_code": r.status_code, "text": r.text}
