import hashlib
import hmac
import time
from urllib.parse import urlparse, parse_qsl, urlencode

import requests

from app.config import (
    FOUR_OVER_APIKEY,
    FOUR_OVER_BASE_URL,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    """
    4over auth: apikey + signature (HMAC-SHA256) over canonical request string.
    Canonical format used here:
      canonical = path + ("?" + sorted_querystring if any)
    Signature:
      hex(hmac_sha256(private_key, canonical))
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        self.base = FOUR_OVER_BASE_URL.rstrip("/")
        self.apikey = FOUR_OVER_APIKEY
        self.private_key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")

    def _sign(self, path: str, params: dict | None) -> dict:
        params = dict(params or {})
        params["apikey"] = self.apikey

        # build sorted query for canonical string
        items = sorted(params.items(), key=lambda x: x[0])
        query = urlencode(items, doseq=True)

        canonical = f"{path}?{query}" if query else path
        sig = hmac.new(self.private_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

        params["signature"] = sig
        return params

    def get(self, path: str, params: dict | None = None):
        if not path.startswith("/"):
            path = "/" + path

        signed_params = self._sign(path, params)
        url = f"{self.base}{path}"

        resp = requests.get(url, params=signed_params, timeout=FOUR_OVER_TIMEOUT)
        return resp.status_code, resp.json() if resp.content else None

    def get_by_full_url(self, full_url: str, extra_params: dict | None = None):
        """
        4over returns full URLs sometimes. We safely convert them back to path+params,
        re-sign, and call via base URL.
        """
        u = urlparse(full_url)
        path = u.path

        existing = dict(parse_qsl(u.query, keep_blank_values=True))
        merged = {**existing, **(extra_params or {})}

        return self.get(path, merged)
