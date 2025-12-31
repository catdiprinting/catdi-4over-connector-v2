# fourover_client.py
import os
import hmac
import hashlib
import requests
from urllib.parse import urlencode

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "").strip()
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "").strip()

def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def signature_for_method(method: str) -> str:
    """
    Per 4over docs: signature = HMAC_SHA256(HTTP_METHOD, SHA256(private_key))
    i.e. message = "GET" / "POST" etc
         key     = sha256(private_key)
    :contentReference[oaicite:1]{index=1}
    """
    if not FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing")
    key_hex = _sha256_hex(FOUR_OVER_PRIVATE_KEY)
    key_bytes = bytes.fromhex(key_hex)
    msg = method.upper().encode("utf-8")
    return hmac.new(key_bytes, msg, hashlib.sha256).hexdigest()

def get(path: str, params: dict | None = None, timeout: int = 30):
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")

    params = params or {}
    params["apikey"] = FOUR_OVER_APIKEY
    params["signature"] = signature_for_method("GET")

    url = f"{FOUR_OVER_BASE_URL}{path}"
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def post(path: str, json_body: dict | None = None, timeout: int = 30):
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")

    sig = signature_for_method("POST")
    headers = {"Authorization": f"API {FOUR_OVER_APIKEY}:{sig}"}
    url = f"{FOUR_OVER_BASE_URL}{path}"

    r = requests.post(url, json=json_body or {}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()
