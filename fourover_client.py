import hashlib
import hmac
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


def _clean(s: str) -> str:
    return (s or "").strip()


class FourOverClient:
    """
    Implements 4over API Key Authentication exactly as documented:

    Signature:
      hmac_key = sha256(private_key).hexdigest()
      signature = HMAC_SHA256(hmac_key, HTTP_METHOD)

    GET/DELETE: signature passed as query param alongside apikey
      ?apikey={PUBLIC_KEY}&signature={SIGNATURE}

    POST/PUT/PATCH: signature passed via header
      Authorization: API {PUBLIC_KEY}:{SIGNATURE}

    NOTE: Per docs, signature depends on HTTP_METHOD ONLY (not path/query).
    """

    def __init__(self, api_key: str, private_key: str, base_url: str = "https://api.4over.com"):
        api_key = _clean(api_key)
        private_key = _clean(private_key)
        base_url = _clean(base_url) or "https://api.4over.com"

        if not api_key:
            raise ValueError("Missing FOUR_OVER_APIKEY")
        if not private_key or len(private_key) < 16:
            raise ValueError(f"Missing/invalid FOUR_OVER_PRIVATE_KEY (len={len(private_key)})")
        self.api_key = api_key
        self.private_key = private_key
        self.base_url = base_url.rstrip("/")

        self.session = requests.Session()
        self.timeout = (5, 25)

    def _signature_for_method(self, method: str) -> str:
        method = method.upper()

        # Doc: hash('sha256', myPrivateKey)
        hmac_key = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest().encode("utf-8")

        # Doc: HMAC(message=HTTP_METHOD)
        msg = method.encode("utf-8")

        return hmac.new(hmac_key, msg, hashlib.sha256).hexdigest()

    def build_get_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not path.startswith("/"):
            path = "/" + path

        sig = self._signature_for_method("GET")

        query = dict(params or {})
        query["apikey"] = self.api_key
        query["signature"] = sig

        qs = urlencode(sorted((k, str(v)) for k, v in query.items() if v is not None))

        return {
            "url": f"{self.base_url}{path}?{qs}",
            "signature": sig,
            "method": "GET",
            "path": path,
            "query": query,
        }

    def get_raw(self, path: str, params: Optional[Dict[str, Any]] = None):
        built = self.build_get_url(path, params=params)
        resp = self.session.get(built["url"], timeout=self.timeout)
        return resp, built

    def whoami(self):
        return self.get_raw("/whoami")

    def products(self, max: int = 20, offset: int = 0, q: Optional[str] = None):
        params: Dict[str, Any] = {"max": max, "offset": offset}
        if q:
            params["q"] = q
        return self.get_raw("/products", params=params)
