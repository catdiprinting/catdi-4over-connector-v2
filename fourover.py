# fourover.py
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from config import settings


class FourOverError(Exception):
    pass


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep)


def _clean_env_value(v: str) -> str:
    """
    Common Railway/CI issues:
      - values wrapped in quotes
      - multiline keys stored with literal "\n"
      - leading/trailing whitespace
    """
    if v is None:
        return ""
    v = str(v).strip()

    # strip wrapping quotes if present
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()

    # convert literal backslash-n to real newline
    v = v.replace("\\n", "\n")
    return v.strip()


@dataclass
class FourOverCredentials:
    base_url: str
    apikey: str
    private_key: str

    @classmethod
    def from_settings(cls) -> "FourOverCredentials":
        base_url = _clean_env_value(settings.FOUR_OVER_BASE_URL or "https://api.4over.com").rstrip("/")
        apikey = _clean_env_value(settings.FOUR_OVER_APIKEY or "")
        private_key = _clean_env_value(settings.FOUR_OVER_PRIVATE_KEY or "")
        return cls(base_url=base_url, apikey=apikey, private_key=private_key)

    def validate(self) -> None:
        if not self.apikey or not self.private_key:
            raise FourOverError(
                "Missing 4over credentials in env. "
                f"FOUR_OVER_APIKEY='{_mask(self.apikey)}' "
                f"FOUR_OVER_PRIVATE_KEY='{_mask(self.private_key)}'"
            )


class FourOverClient:
    """
    Signing pattern:
      canonical = "/path?apikey=XXX&k=v" (sorted query params, NO signature)
      signature = HMAC_SHA256(private_key, canonical).hexdigest()
    Request:
      GET {base}{path}?apikey=...&...&signature=...
    """

    def __init__(self, creds: Optional[FourOverCredentials] = None):
        self.creds = creds or FourOverCredentials.from_settings()

    def _canonical(self, path: str, params: Optional[Dict[str, Any]]) -> str:
        if not path.startswith("/"):
            path = "/" + path

        qp: Dict[str, Any] = {"apikey": self.creds.apikey}

        if params:
            for k, v in params.items():
                if v is None or k == "signatu
::contentReference[oaicite:0]{index=0}
