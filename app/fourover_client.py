import hashlib
import hmac
import requests
from urllib.parse import urlparse, urlencode

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_TIMEOUT,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
)


class FourOverClient:
    """
    4over authentication:
    signature = HMAC_SHA256(
        message = HTTP_METHOD,
        key     = SHA256(PRIVATE_KEY)
    )

    GET requests use query params: apikey + signature
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY")
        if not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_PRIVATE_KEY")

        self.base_url = FOUR_OVER_BASE_URL.rstrip("/")
        self.prefix = FOUR_OVER_API_PREFIX.strip("/")
        self.apikey = FOUR_OVER_APIKEY.strip()
        self.private_key = FOUR_OVER_PRIVATE_KEY.strip()
        self.timeout = int(FOUR_OVER_TIMEOUT)

    def _signature(self, method: str) -> str:
        key = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()
        return hmac.new(
            key.encode("utf-8"),
            method.upper().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _path(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path

        # whoami lives at root
        if path == "/whoami":
            return path

        if self.prefix and not path.startswith(f"/{self.prefix}/"):
            return f"/{self.prefix}{path}"

        return path

    def get(self, path: str, params: dict | None = None):
        sig = self._signature("GET")
        url = f"{self.base_url}{self._path(path)}"

        qp = {"apikey": self.apikey, "signature": sig}
        if params:
            for k, v in params.items():
                if v is not None:
                    qp[k] = v

        return requests.get(url, params=qp, timeout=self.timeout)

    def get_url(self, full_url: str, params: dict | None = None):
        """
        Used for option_prices URLs returned by 4over
        """
        sig = self._signature("GET")

        qp = {"apikey": self.apikey, "signature": sig}
        if params:
            for k, v in params.items():
                if v is not None:
                    qp[k] = v

        parsed = urlparse(full_url)
        existing = parsed.query
        extra = urlencode(qp)

        if existing:
            url = full_url + "&" + extra
        else:
            url = full_url + "?" + extra

        return requests.get(url, timeout=self.timeout)
