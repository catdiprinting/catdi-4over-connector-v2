import hmac
import hashlib
import json
import requests
from urllib.parse import urlencode

from config import FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY, FOUR_OVER_BASE_URL, DEBUG

class FourOverError(Exception):
    pass

def _canonical_path_and_query(path: str, params: dict | None) -> tuple[str, str]:
    """
    4over signing is picky. This builds:
      canonical = /path?apikey=...&other=...
    with query params sorted by key and urlencoded.
    """
    if not path.startswith("/"):
        path = "/" + path

    params = params or {}
    # Ensure apikey always present in canonical query
    params = {**params, "apikey": FOUR_OVER_APIKEY}

    # Sort params for stable canonical
    items = sorted(params.items(), key=lambda kv: kv[0])
    qs = urlencode(items, doseq=True)

    canonical = f"{path}?{qs}" if qs else path
    return canonical, qs

def _sign(private_key: str, canonical: str) -> str:
    """
    HMAC-SHA256 signature hex.
    """
    if not private_key:
        raise FourOverError("FOUR_OVER_PRIVATE_KEY missing")
    msg = canonical.encode("utf-8")
    key = private_key.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

class FourOverClient:
    def __init__(self):
        if not FOUR_OVER_APIKEY:
            raise FourOverError("FOUR_OVER_APIKEY missing")
        if not FOUR_OVER_PRIVATE_KEY:
            raise FourOverError("FOUR_OVER_PRIVATE_KEY missing")

        self.base = FOUR_OVER_BASE_URL

    def request(self, method: str, path: str, params: dict | None = None):
        canonical, qs = _canonical_path_and_query(path, params)
        signature = _sign(FOUR_OVER_PRIVATE_KEY, canonical)

        # 4over expects signature as query param
        url = f"{self.base}{path}"
        full_params = dict(params or {})
        full_params["apikey"] = FOUR_OVER_APIKEY
        full_params["signature"] = signature

        r = requests.request(method.upper(), url, params=full_params, timeout=45)

        # Try parse JSON always
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        debug = None
        if DEBUG:
            debug = {
                "url": r.url,
                "base": self.base,
                "canonical": canonical,
                "signature": signature,
                "status_code": r.status_code,
                "response_preview": (r.text[:500] if isinstance(r.text, str) else str(r.text)[:500]),
            }

        if r.status_code >= 400:
            raise FourOverError(json.dumps({"status": r.status_code, "data": data, "debug": debug}, ensure_ascii=False))

        return data, debug

    # Convenience wrappers
    def whoami(self):
        return self.request("GET", "/whoami")

    def categories(self):
        # 4over endpoint typically looks like /printproducts/categories
        return self.request("GET", "/printproducts/categories")

    def category_products(self, category_uuid: str, pages: int = 1):
        # 4over endpoint typically looks like:
        # /printproducts/categories/{uuid}/products
        return self.request("GET", f"/printproducts/categories/{category_uuid}/products", params={"pages": pages})

    def product_options(self, product_uuid: str):
        # You were hitting something like:
        # /printproducts/{product_uuid}
        # and/or options endpoints; this is a safe "details" read:
        return self.request("GET", f"/printproducts/{product_uuid}")
