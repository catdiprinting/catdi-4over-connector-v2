import os
import time
import json
import hmac
import hashlib
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests


class FourOverAuthError(Exception):
    pass


def _env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _clean_base_url(url: str) -> str:
    return url.rstrip("/")


def _canonical(path: str, params: Dict[str, Any]) -> str:
    """
    Canonical format that has proven consistent with the 4over debug you've shown:
    "/whoami?apikey=catdi" (no signature included)
    """
    # Ensure deterministic ordering
    items = sorted((k, str(v)) for k, v in params.items() if v is not None)
    qs = urlencode(items)
    return f"{path}?{qs}" if qs else path


def _sig_hmac_sha256(private_key: str, canonical: str) -> str:
    return hmac.new(private_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _sig_concat_sha256(private_key: str, canonical: str) -> str:
    # fallback mode used by some APIs: sha256(private_key + canonical)
    return hashlib.sha256((private_key + canonical).encode("utf-8")).hexdigest()


def _build_signed_url(
    base_url: str,
    path: str,
    apikey: str,
    private_key: str,
    params: Optional[Dict[str, Any]] = None,
    signing_mode: str = "hmac",
) -> Tuple[str, str, str]:
    """
    Returns (full_url, canonical, signature) WITHOUT mutating caller's params.
    """
    params = dict(params or {})
    params["apikey"] = apikey

    canonical = _canonical(path, params)

    if signing_mode == "concat":
        signature = _sig_concat_sha256(private_key, canonical)
    else:
        signature = _sig_hmac_sha256(private_key, canonical)

    # Final request params include signature
    signed_params = dict(params)
    signed_params["signature"] = signature

    url = f"{_clean_base_url(base_url)}{path}?{urlencode(sorted((k, str(v)) for k, v in signed_params.items()))}"
    return url, canonical, signature


def fourover_request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Makes a request to 4over with a "works-first" approach:
    - Try HMAC signature first
    - If 401, retry once with concat signature
    """
    base_url = _env_required("FOUR_OVER_BASE_URL")
    apikey = _env_required("FOUR_OVER_APIKEY")
    private_key = _env_required("FOUR_OVER_PRIVATE_KEY")

    method_u = method.upper()

    # Try modes in order
    for mode in ("hmac", "concat"):
        url, canonical, signature = _build_signed_url(
            base_url=base_url,
            path=path,
            apikey=apikey,
            private_key=private_key,
            params=params,
            signing_mode=mode,
        )

        try:
            resp = requests.request(
                method=method_u,
                url=url,
                json=json_body if json_body is not None else None,
                timeout=timeout,
            )
        except requests.RequestException as e:
            return {
                "ok": False,
                "http_code": None,
                "error": str(e),
                "debug": {"mode": mode, "url": url, "canonical": canonical, "signature": signature},
            }

        # If unauthorized on first mode, retry with the fallback mode
        if resp.status_code == 401 and mode == "hmac":
            continue

        # Parse json (4over usually returns json)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {
            "ok": resp.ok,
            "http_code": resp.status_code,
            "response": data,
            "debug": {"mode": mode, "url": url, "canonical": canonical, "signature": signature},
        }

    # If both failed (should never hit due to return)
    raise FourOverAuthError("Failed to authenticate with both signature modes.")


def fourover_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
    return fourover_request("GET", path, params=params, timeout=timeout)


def fourover_post(path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None, timeout: int = 60) -> Dict[str, Any]:
    return fourover_request("POST", path, params=params, json_body=json_body, timeout=timeout)
