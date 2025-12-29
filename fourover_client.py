import os
import time
import hashlib
import hmac
import requests
from urllib.parse import urlencode, urljoin


def normalize_private_key(pk: str) -> str:
    # Env vars frequently carry trailing newlines/spaces
    return (pk or "").strip()


def build_canonical_path_and_query(path: str, query: dict) -> str:
    # Must include apikey; must exclude signature
    items = sorted(
        (k, str(v))
        for k, v in (query or {}).items()
        if v is not None and k != "signature"
    )
    qs = urlencode(items)
    return f"{path}?{qs}" if qs else path


def sign_4over_request(method: str, canonical_path_and_query: str, private_key: str) -> str:
    pk = normalize_private_key(private_key)
    # per project discovery: hmac_key = sha256(private_key) THEN HMAC_SHA256(...)
    hmac_key = hashlib.sha256(pk.encode("utf-8")).hexdigest().encode("utf-8")
    message = (method.upper() + canonical_path_and_query).encode("utf-8")
    return hmac.new(hmac_key, message, hashlib.sha256).hexdigest()


class FourOverClient:
    """
    Single canonical client. All signing happens here.
    """

    def __init__(
        self,
        base_url: str | None = None,
        apikey: str | None = None,
        private_key: str | None = None,
        timeout_connect: float = 5.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.6,
    ):
        self.base_url = (base_url or os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")).rstrip("/")
        self.apikey = apikey or os.getenv("FOUR_OVER_APIKEY", "")
        self.private_key = private_key or os.getenv("FOUR_OVER_PRIVATE_KEY", "")
        self.timeout = (timeout_connect, timeout_read)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

        # Session for keep-alive
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _signed_params(self, method: str, path: str, params: dict | None):
        params = dict(params or {})
        params["apikey"] = self.apikey

        canonical = build_canonical_path_and_query(path, params)
        signature = sign_4over_request(method, canonical, self.private_key)

        # Actual request params include signature
        signed = dict(params)
        signed["signature"] = signature
        return signed, canonical, signature

    def request(self, method: str, path: str, params: dict | None = None):
        method = method.upper()
        signed_params, canonical, signature = self._signed_params(method, path, params)

        url = urljoin(self.base_url + "/", path.lstrip("/"))

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=signed_params,
                    timeout=self.timeout,
                )

                # Retry on throttling or transient server errors
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                        continue

                return resp, {"url": url, "canonical": canonical, "signature": signature}

            except requests.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1)))
                    continue
                raise

        # Should never hit, but just in case
        raise last_exc or RuntimeError("Unknown request failure")

    def debug_sign(self, method: str, path: str, params: dict | None = None):
        method = method.upper()
        signed_params, canonical, signature = self._signed_params(method, path, params)
        # Return signed params too (apikey masked in caller)
        return signed_params, canonical, signature
