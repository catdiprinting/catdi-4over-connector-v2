# fourover_client.py
import os
import hmac
import hashlib
import requests
from typing import Any, Dict, Optional

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "").strip()
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "").strip()


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def signature_for_method(method: str) -> str:
    """
    4over docs:
      signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
    Important nuance:
      PHP's hash('sha256', $privateKey) returns HEX STRING,
      and hash_hmac uses that HEX STRING as the key (ASCII).
    So we should use key_hex.encode('utf-8') (NOT bytes.fromhex()).
    """
    if not FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing")

    key_hex = _sha256_hex(FOUR_OVER_PRIVATE_KEY)          # hex string
    key_bytes = key_hex.encode("utf-8")                   # ASCII bytes (matches PHP behavior)
    msg = method.upper().encode("utf-8")                  # "GET", "POST", etc.

    return hmac.new(key_bytes, msg, hashlib.sha256).hexdigest()


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
        # sometimes APIs return lists; wrap it for consistency
        return {"_raw_list": data}
    except Exception:
        return {"_raw_text": (resp.text or "")[:3000]}


def get_raw(path: str, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")

    params = dict(params or {})
    params["apikey"] = FOUR_OVER_APIKEY
    params["signature"] = signature_for_method("GET")

    url = f"{FOUR_OVER_BASE_URL}{path}"
    return requests.get(url, params=params, timeout=timeout)


def get(path: str, params: Optional[dict] = None, timeout: int = 30) -> Dict[str, Any]:
    """
    Backwards-compatible helper: returns parsed JSON on 200, raises requests.HTTPError otherwise.
    Prefer using get_raw() in routers so we can return upstream error details.
    """
    r = get_raw(path, params=params, timeout=timeout)
    r.raise_for_status()
    return _safe_json(r)


def post_raw(path: str, json_body: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")

    sig = signature_for_method("POST")
    headers = {"Authorization": f"API {FOUR_OVER_APIKEY}:{sig}", "Accept": "application/json"}

    url = f"{FOUR_OVER_BASE_URL}{path}"
    return requests.post(url, json=json_body or {}, headers=headers, timeout=timeout)


def post(path: str, json_body: Optional[dict] = None, timeout: int = 30) -> Dict[str, Any]:
    r = post_raw(path, json_body=json_body, timeout=timeout)
    r.raise_for_status()
    return _safe_json(r)
