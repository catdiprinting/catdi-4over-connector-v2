import os
import json
import hmac
import hashlib
import requests
from dataclasses import dataclass
from typing import Any, Dict, Optional


class FourOverError(Exception):
    def __init__(self, status: int, url: str, body: str, canonical: str = ""):
        super().__init__(f"4over request failed: {status} {url}")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def _env_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _signature_for_method(http_method: str, private_key: str) -> str:
    """
    Per 4over docs (from your PDF):
      private_key_hash = sha256(private_key)
      signature = hmac_sha256(message=HTTP_METHOD, key=private_key_hash)
    Notes:
      - docs show using the *hashed* private key as the HMAC key
      - message is the HTTP method only (GET/POST/PUT/DELETE)
    """
    method = http_method.upper().strip()

    # docs show sha256(private_key) then use that as key
    private_key_hash_hex = hashlib.sha256(private_key.encode("utf-8")).hexdigest()

    sig = hmac.new(
        key=private_key_hash_hex.encode("utf-8"),
        msg=method.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return sig


@dataclass
class FourOverClient:
    base_url: str
    apikey: str
    private_key: str
    timeout: int = 30

    def request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = method.upper().strip()
        if not path.startswith("/"):
            path = "/" + path

        signature = _signature_for_method(method, self.private_key)

        url = self.base_url.rstrip("/") + path

        # GET/DELETE: signature + apikey go as query params (per docs)
        req_params = dict(params or {})
        req_headers: Dict[str, str] = {}

        if method in ("GET", "DELETE"):
            req_params["apikey"] = self.apikey
            req_params["signature"] = signature
        else:
            # POST/PUT: docs show Authorization header pattern.
            # We keep apikey as query too for consistency; some endpoints accept both.
            req_params["apikey"] = self.apikey
            req_headers["Authorization"] = f"{self.apikey}:{signature}"

        try:
            resp = requests.request(
                method=method,
                url=url,
                params=req_params,
                json=json_body,
                headers=req_headers,
                timeout=self.timeout,
            )
        except Exception as e:
            raise FourOverError(status=0, url=url, body=str(e), canonical=path)

        body_text = resp.text or ""
        if resp.status_code >= 400:
            raise FourOverError(status=resp.status_code, url=resp.url, body=body_text, canonical=path)

        if not body_text:
            return {}

        try:
            return resp.json()
        except Exception:
            # if 4over returns non-json
            return {"raw": body_text}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request_json("GET", path, params=params)

    def post(self, path: str, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request_json("POST", path, params=params, json_body=json_body)


# Export a "client" object to satisfy any existing router code that does:
#   from fourover_client import client
def _build_client() -> FourOverClient:
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
    apikey = _env_required("FOUR_OVER_APIKEY")
    private_key = _env_required("FOUR_OVER_PRIVATE_KEY")
    return FourOverClient(base_url=base_url, apikey=apikey, private_key=private_key)


client = _build_client()


# Convenience functions used by main.py (safe wrappers)
def whoami() -> Dict[str, Any]:
    return client.get("/whoami")


def product_baseprices(product_uuid: str) -> Dict[str, Any]:
    return client.get(f"/printproducts/products/{product_uuid}/baseprices")


def product_optiongroups(product_uuid: str) -> Dict[str, Any]:
    return client.get(f"/printproducts/products/{product_uuid}/optiongroups")


def auth_debug() -> Dict[str, Any]:
    """
    Returns signatures for each method WITHOUT revealing secrets.
    """
    priv = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
    if not priv:
        return {"ok": False, "error": "FOUR_OVER_PRIVATE_KEY missing"}

    return {
        "ok": True,
        "base_url": os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        "apikey_present": bool(os.getenv("FOUR_OVER_APIKEY")),
        "private_key_present": True,
        "signatures": {
            "GET": _signature_for_method("GET", priv),
            "POST": _signature_for_method("POST", priv),
            "PUT": _signature_for_method("PUT", priv),
            "DELETE": _signature_for_method("DELETE", priv),
        },
    }
