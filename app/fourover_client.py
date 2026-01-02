import hashlib
import hmac
import requests
from typing import Optional, Dict, Any

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_TIMEOUT,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
)


class FourOverClient:
    """
    4over Auth (per your working PHP + docs):
      signature = HMAC_SHA256( message=HTTP_METHOD, key=SHA256(PRIVATE_KEY) )

    GET/DELETE:
      send apikey + signature in QUERY STRING

    POST/PUT/PATCH:
      send Authorization header:
        Authorization: API {apikey}:{signature}
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        self.base_url = (FOUR_OVER_BASE_URL or "").rstrip("/")
        self.prefix = (FOUR_OVER_API_PREFIX or "").strip("/")

        self.apikey = (FOUR_OVER_APIKEY or "").strip()
        self.private_key = (FOUR_OVER_PRIVATE_KEY or "").strip()

        try:
            self.timeout = int(FOUR_OVER_TIMEOUT)
        except Exception:
            self.timeout = 30

        if not self.base_url:
            raise RuntimeError("Missing FOUR_OVER_BASE_URL")

    # ---------- path helpers ----------

    def _api_path(self, path: str) -> str:
        """
        whoami lives at root: /whoami
        catalog lives under prefix: /printproducts/...
        """
        if not path.startswith("/"):
            path = "/" + path

        # Whoami is at root.
        if path == "/whoami" or path.startswith("/whoami?"):
            return "/whoami"

        # If already prefixed, don't double-prefix
        if self.prefix and path.startswith(f"/{self.prefix}/"):
            return path

        if self.prefix:
            return f"/{self.prefix}{path}"

        return path

    # ---------- auth/signature ----------

    def signature_for_method(self, method: str) -> str:
        """
        signature = HMAC_SHA256( message=HTTP_METHOD, key=SHA256(PRIVATE_KEY) )
        """
        method = (method or "").upper().strip()
        if not method:
            raise ValueError("HTTP method required")

        hashed_key_hex = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()
        sig = hmac.new(
            hashed_key_hex.encode("utf-8"),
            method.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return sig

    # ---------- request wrappers ----------

    def get(self, path: str, params: Optional[Dict[str, Any]] = None):
        api_path = self._api_path(path)
        url = f"{self.base_url}{api_path}"

        sig = self.signature_for_method("GET")
        qp = {"apikey": self.apikey, "signature": sig}
        if params:
            qp.update({k: v for k, v in params.items() if v is not None})

        return requests.get(url, params=qp, timeout=self.time
