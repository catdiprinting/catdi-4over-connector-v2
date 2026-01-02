import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
    FOUR_OVER_TIMEOUT,
)


class FourOverClient:
    """
    Builds signed requests like:
      BASE_URL + /{prefix}/{path}?apikey=...&signature=...

    IMPORTANT:
    - Some endpoints (like /whoami) are NOT under the prefix.
    - So we support use_prefix=False for those.
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            # don’t crash import; raise only when used
            self.ready = False
        else:
            self.ready = True

        self.base = FOUR_OVER_BASE_URL
        self.prefix = FOUR_OVER_API_PREFIX.strip("/")

    def _signature(self, canonical: str) -> str:
        # 4over expects HMAC-SHA256 of canonical using the private key
        key = FOUR_OVER_PRIVATE_KEY.encode("utf-8")
        msg = canonical.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def _build_url(self, path: str, params: dict | None = None, use_prefix: bool = True) -> tuple[str, str]:
        """
        Returns (url, canonical_path_with_query)
        canonical is what gets signed (path + querystring excluding signature)
        """

        if not self.ready:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        params = dict(params or {})

        # Always include apikey in signed query
        params["apikey"] = FOUR_OVER_APIKEY

        # Clean path
        path = path.strip("/")
        full_path = path

        if use_prefix:
            # Avoid prefix duplication defensively
            if full_path.startswith(self.prefix + "/"):
                pass
            else:
                full_path = f"{self.prefix}/{full_path}"

        canonical = "/" + full_path
        qs = urlencode(params)
        canonical_with_qs = canonical + ("?" + qs if qs else "")

        sig = self._signature(canonical_with_qs)
        url = f"{self.base}{canonical_with_qs}&signature={sig}"

        return url, canonical_with_qs

    def get(self, path: str, params: dict | None = None, use_prefix: bool = True):
        url, _canonical = self._build_url(path, params=params, use_prefix=use_prefix)
        try:
            r = requests.get(url, timeout=FOUR_OVER_TIMEOUT)
            content_type = r.headers.get("content-type", "")
            if "application/json" in content_type:
                return r.status_code, r.json()
            return r.status_code, {"raw": r.text}
        except Exception as e:
            return 599, {"status": "error", "message": str(e), "url": url}

    def post(self, path: str, json_body: dict | None = None, params: dict | None = None, use_prefix: bool = True):
        url, _canonical = self._build_url(path, params=params, use_prefix=use_prefix)
        try:
            r = requests.post(url, json=json_body or {}, timeout=FOUR_OVER_TIMEOUT)
            content_type = r.headers.get("content-type", "")
            if "application/json" in content_type:
                return r.status_code, r.json()
            return r.status_code, {"raw": r.text}
        except Exception as e:
            return 599, {"status": "error", "message": str(e), "url": url}
