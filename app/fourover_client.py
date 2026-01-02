import os
import hmac
import hashlib
import requests
from urllib.parse import urlencode


class FourOverClient:
    """
    4over auth notes (based on your working debug/auth output):
      - GET uses query auth: ?apikey=XXX&signature=YYY
      - POST uses header: Authorization: API apikey:signature
    Signature is HMAC-SHA256(private_key, canonical_string)
    canonical_string example from your debug:
      "/whoami?apikey=catdi"
    """

    def __init__(self):
        self.base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
        self.api_prefix = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")

        self.apikey = os.getenv("FOUR_OVER_APIKEY", "")
        self.private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

        # Keep it string for debug readability; convert to int when used
        self.timeout = os.getenv("FOUR_OVER_TIMEOUT", "30")

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

    def _hmac_sha256(self, message: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _canonical(self, path: str, params: dict | None = None) -> str:
        """
        Canonical form is path + ? + sorted query (if any).
        Example: "/whoami?apikey=catdi"
        """
        if not params:
            return path
        # sort params for stable signing
        items = sorted((k, str(v)) for k, v in params.items() if v is not None)
        return f"{path}?{urlencode(items)}"

    def _url(self, path: str) -> str:
        # If path is already a full URL from 4over, use it.
        if path.startswith("http://") or path.startswith("https://"):
            return path
        # Otherwise assume it's an API path
        return f"{self.base_url}/{path.lstrip('/')}"

    def get(self, path: str, params: dict | None = None) -> requests.Response:
        """
        GET uses query auth: apikey + signature.
        The signature is computed from canonical = path + ? + query(apikey + other params)
        """
        params = dict(params or {})
        params["apikey"] = self.apikey

        # Determine the signing path:
        # If path is full url, extract the pathname part for canonical signing
        signing_path = path
        if signing_path.startswith("http://") or signing_path.startswith("https://"):
            # Convert full URL to just the path part for canonical signing
            # Example: https://api.4over.com/printproducts/categories -> /printproducts/categories
            signing_path = "/" + signing_path.split("://", 1)[1].split("/", 1)[1]
            signing_path = "/" + signing_path.split("/", 1)[1] if not signing_path.startswith("/") else signing_path

        # If caller passes /printproducts/... directly, keep it
        if not signing_path.startswith("/"):
            signing_path = "/" + signing_path

        canonical = self._canonical(signing_path, params)
        signature = self._hmac_sha256(canonical)
        params["signature"] = signature

        url = self._url(path)
        return requests.get(url, params=params, timeout=int(self.timeout))

    def post(self, path: str, json_body: dict | None = None, params: dict | None = None) -> requests.Response:
        """
        POST uses Authorization header:
          Authorization: API apikey:signature
        Signature computed from canonical = path (+ ?query if params)
        """
        params = dict(params or {})

        signing_path = path
        if signing_path.startswith("http://") or signing_path.startswith("https://"):
            signing_path = "/" + signing_path.split("://", 1)[1].split("/", 1)[1]
            signing_path = "/" + signing_path.split("/", 1)[1] if not signing_path.startswith("/") else signing_path

        if not signing_path.startswith("/"):
            signing_path = "/" + signing_path

        canonical = self._canonical(signing_path, params if params else None)
        signature = self._hmac_sha256(canonical)

        headers = {
            "Authorization": f"API {self.apikey}:{signature}",
            "Content-Type": "application/json",
        }

        url =
