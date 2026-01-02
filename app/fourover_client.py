import hashlib
import hmac
import requests

from app.config import (
    FOUR_OVER_BASE_URL,
    FOUR_OVER_API_PREFIX,
    FOUR_OVER_TIMEOUT,
    FOUR_OVER_APIKEY,
    FOUR_OVER_PRIVATE_KEY,
)


class FourOverClient:
    """
    signature = HMAC_SHA256(
        message = HTTP_METHOD,
        key     = SHA256(PRIVATE_KEY)
    )
    """

    def __init__(self):
        if not FOUR_OVER_APIKEY:
            raise RuntimeError("Missing FOUR_OVER_APIKEY")
        if not FOUR_OVER_PRIVATE_KEY:
            raise RuntimeError("Missing FOUR_OVER_PRIVATE_KEY")

        self.base_url = FOUR_OVER_BASE_URL.rstrip("/")
        self.prefix = FOUR_OVER_API_PREFIX.strip("/")
        self.apikey = FOUR_OVER_APIKEY
        self.private_key = FOUR_OVER_PRIVATE_KEY
        self.timeout = int(FOUR_OVER_TIMEOUT)

    def _path(self, path: str):
        if not path.startswith("/"):
            path = "/" + path

        # whoami always lives at root
        if path == "/whoami":
            return path

        if self.prefix and not path.startswith(f"/{self.prefix}/"):
            return f"/{self.prefix}{path}"

        return path

    def _signature(self, method: str):
        key = hashlib.sha256(self.private_key.encode()).hexdigest()
        return hmac.new(
            key.encode(),
            method.upper().encode(),
            hashlib.sha256,
        ).hexdigest()

    def get(self, path: str, params: dict | None = None):
        sig = self._signature("GET")
        url = f"{self.base_url}{self._path(path)}"

        qp = {"apikey": self.apikey, "signature": sig}
        if params:
            qp.update(params)

        return requests.get(url, params=qp, timeout=self.timeout)
