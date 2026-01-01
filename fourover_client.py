# fourover_client.py
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests


# -----------------------------
# Errors
# -----------------------------
class FourOverError(Exception):
    """Base error for all 4over client failures."""


class FourOverAuthError(FourOverError):
    """Raised when 4over returns 401/403 or auth is invalid."""


class FourOverRequestError(FourOverError):
    """Raised for non-auth HTTP errors or unexpected responses."""


# -----------------------------
# Helpers
# -----------------------------
def _strip(s: Optional[str]) -> str:
    return (s or "").strip()


def _canonical_path_and_query(path: str, query: Dict[str, Any]) -> str:
    """
    Canonical string = path + '?' + querystring (sorted by key)
    Must include apikey and any other params used in the request.
    """
    items = sorted([(k, str(v)) for k, v in query.items() if v is not None], key=lambda x: x[0])
    qs = urlencode(items)
    return f"{path}?{qs}" if qs else path


def _hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class FourOverClient:
    base_url: str
    apikey: str
    private_key: str
    timeout: int = 60

    @classmethod
    def from_env(cls) -> "FourOverClient":
        base_url = _strip(os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"))
        apikey = _strip(os.getenv("FOUR_OVER_APIKEY"))
        private_key = _strip(os.getenv("FOUR_OVER_PRIVATE_KEY"))

        if not apikey:
            raise FourOverAuthError("Missing FOUR_OVER_APIKEY in environment.")
        if not private_key:
            raise FourOverAuthError("Missing FOUR_OVER_PRIVATE_KEY in environment.")

        return cls(base_url=base_url, apikey=apikey, private_key=private_key)

    def sign(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        params = dict(params or {})
        params["apikey"] = self.apikey
        canonical = _canonical_path_and_query(path, params)
        signature = _hmac_sha256_hex(self.private_key, canonical)
        return canonical, signature

    def build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        params = dict(params or {})
        params["apikey"] = self.apikey

        canonical = _canonical_path_and_query(path, params)
        signature = _hmac_sha256_hex(self.private_key, canonical)

        params["signature"] = signature

        base = self.base_url.rstrip("/")
        qs = urlencode(sorted([(k, str(v)) for k, v in params.items() if v is not None], key=lambda x: x[0]))
        return f"{base}{path}?{qs}"

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.build_url(path, params=params)

        try:
            resp = requests.get(url, timeout=self.timeout)
        except Exception as e:
            raise FourOverRequestError(f"Request failed: {e}") from e

        body = resp.text or ""

        if resp.status_code in (401, 403):
            canonical, _sig = self.sign(path, params or {})
            raise FourOverAuthError(
                json.dumps(
                    {
                        "error": "4over_auth_failed",
                        "status": resp.status_code,
                        "url": url,
                        "body": body[:2000],
                        "canonical": canonical,
                    }
                )
            )

        if resp.status_code >= 400:
            canonical, _sig = self.sign(path, params or {})
            raise FourOverRequestError(
                json.dumps(
                    {
                        "error": "4over_request_failed",
                        "status": resp.status_code,
                        "url": url,
                        "body": body[:2000],
                        "canonical": canonical,
                    }
                )
            )

        try:
            return resp.json()
        except Exception as e:
            raise FourOverRequestError(f"Non-JSON response ({resp.status_code}): {body[:2000]}") from e

    # Convenience
    def whoami(self) -> Dict[str, Any]:
        return self.get_json("/whoami")
