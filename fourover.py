# fourover.py
from __future__ import annotations

import hmac
import hashlib
from urllib.parse import urlencode

import requests
from config import settings


class FourOverError(Exception):
    pass


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep)


class FourOverClient:
    """
    Canonical signing pattern you previously saw in your debug output:
      canonical = "/whoami?apikey=XXX&k=v" (sorted query params, no signature)
      signature = HMAC_SHA256(private_key, canonical).hexdigest()
    Request:
      GET {base}{path}?apikey=...&...&signature=...
    """

    def __init__(self, base_url=None, apikey=None, private_key=None):
        self.base_url = (base_url or settings.FOUR_OVER_BASE_URL).rstrip("/")
        self.apikey = apikey or settings.FOUR_OVER_APIKEY
        self.private_key = private_key or settings.FOUR_OVER_PRIVATE_KEY

        if not self.apikey or not self.private_key:
            raise FourOverError(
                f"Missing 4over credentials. "
                f"FOUR_OVER_APIKEY='{_mask(self.apikey)}' FOUR_OVER_PRIVATE_KEY='{_mask(self.private_key)}'"
            )

    def _canonical(self, path: str, params: dict | None) -> str:
        qp = {"apikey": self.apikey}
        if params:
            for k, v in params.items():
                if v is None or k == "signature":
                    continue
                qp[k] = v

        query = urlencode(sorted(qp.items()), doseq=True)
        return f"{path}?{query}" if query else path

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def request(self, method: str, path: str, params: dict | None = None, json: dict | None = None, timeout: int = 30):
        if not path.startswith("/"):
            path = "/" + path

        canonical = self._canonical(path, params)
        signature = self._sign(canonical)

        final_params = {"apikey": self.apikey, "signature": signature}
        if params:
            for k, v in params.items():
                if v is None or k == "signature":
                    continue
                final_params[k] = v

        url = f"{self.base_url}{path}"
        resp = requests.request(method.upper(), url, params=final_params, json=json, timeout=timeout)

        debug = {
            "url": resp.url,
            "base": self.base_url,
            "canonical": canonical,
            "signature_prefix": signature[:10],
            "status_code": resp.status_code,
        }

        if resp.status_code >= 400:
            raise FourOverError(f"4over request failed: {debug} body={resp.text[:800]}")

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "debug": debug}

    def whoami(self):
        return self.request("GET", "/whoami")
