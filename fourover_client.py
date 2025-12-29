import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

def _clean_env(v: str | None) -> str | None:
    if v is None:
        return None
    return v.strip()

def _first_env(*keys: str) -> str | None:
    for k in keys:
        v = _clean_env(os.getenv(k))
        if v:
            return v
    return None

class FourOverClient:
    """
    Signs requests using:
      key = sha256(private_key).digest()
      msg = METHOD + canonical_path_with_sorted_query (excluding signature)
      signature = hmac_sha256(key, msg).hexdigest()
    """

    def __init__(self, base_url: str | None = None, apikey: str | None = None, private_key: str | None = None):
        self.base_url = (base_url or _first_env("FOUR_OVER_BASE_URL", "FOUROVER_BASE_URL") or "https://api.4over.com").rstrip("/")

        # Accept YOUR Railway env var names + common variants
        self.apikey = apikey or _first_env(
            "FOUR_OVER_APIKEY",
            "FOUR_OVER_API_KEY",
            "FOUROVER_APIKEY",
            "FOUROVER_API_KEY",
            "FOUROVER_APIKEY",
        )

        self.private_key = private_key or _first_env(
            "FOUR_OVER_PRIVATE_KEY",
            "FOUROVER_PRIVATE_KEY",
            "FOUROVER_PRIVATEKEY",
        )

        if not self.apikey or not self.private_key:
            raise RuntimeError("Missing FOUR_OVER_APIKEY (or variant) or FOUR_OVER_PRIVATE_KEY (or variant) in env vars")

        # HMAC key is sha256(private_key) as bytes
        self._hmac_key = hashlib.sha256(self.private_key.encode("utf-8")).digest()

        self._session = requests.Session()
        self._timeout = (10, 60)  # connect, read

    def _canonical(self, path: str, params: dict) -> str:
        """
        Canonical string:
          path + '?' + sorted_query
        Must include apikey; must exclude signature.
        """
        qp = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            if k.lower() == "signature":
                continue
            qp[k] = str(v)

        # Ensure apikey is always present
        qp["apikey"] = self.apikey

        # Sort params by key for stable signing
        items = sorted(qp.items(), key=lambda kv: kv[0])
        query = urlencode(items, doseq=True)

        return f"{path}?{query}" if query else path

    def _sign(self, method: str, canonical: str) -> str:
        msg = (method.upper() + canonical).encode("utf-8")
        return hmac.new(self._hmac_key, msg, hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict | None = None):
        params = dict(params or {})
        canonical = self._canonical(path, params)
        signature = self._sign(method, canonical)

        # Send params including signature + apikey
        send_params = dict(params)
        send_params["apikey"] = self.apikey
        send_params["signature"] = signature

        url = f"{self.base_url}{path}"

        # Light retry for transient 502/504/rate issues
        last_exc = None
        for attempt in range(3):
            try:
                resp = self._session.request(method.upper(), url, params=send_params, timeout=self._timeout)
                if resp.status_code in (502, 503, 504):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                time.sleep(0.5 * (attempt + 1))

        raise last_exc

    def whoami(self):
        return self._request("GET", "/whoami")

    def products(self, offset: int = 0, per_page: int = 200):
        # 4over enforces perPage cap (often 20). We request high but honor returned count.
        return self._request("GET", "/products", params={"offset": offset, "perPage": per_page})
