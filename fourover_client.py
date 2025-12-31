# fourover_client.py
import hashlib
import hmac
import requests
from typing import Any, Dict, Optional
from config import FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY, FOUR_OVER_BASE_URL

class FourOverClient:
    """
    4over auth (per provided PDF):
    - GET/DELETE: ?apikey={PUBLIC_KEY}&signature={SIGNATURE}
    - POST/PUT/PATCH: Authorization: API {PUBLIC_KEY}:{SIGNATURE}
    Signature:
      signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))
    """
    def __init__(self):
        if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY env vars")

        self.public_key = FOUR_OVER_APIKEY.strip()
        self.private_key = FOUR_OVER_PRIVATE_KEY.strip()
        self.base_url = FOUR_OVER_BASE_URL

    def _method_signature(self, method: str) -> str:
        method = method.upper().strip()
        # key = sha256(private_key) hex, then bytes
        key_hex = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()
        key_bytes = key_hex.encode("utf-8")

        sig = hmac.new(key_bytes, method.encode("utf-8"), hashlib.sha256).hexdigest()
        return sig

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = dict(params or {})
        params["apikey"] = self.public_key
        params["signature"] = self._method_signature("GET")

        url = f"{self.base_url}{path}"
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        sig = self._method_signature("POST")
        headers = {"Authorization": f"API {self.public_key}:{sig}"}

        r = requests.post(url, json=json_body or {}, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()
