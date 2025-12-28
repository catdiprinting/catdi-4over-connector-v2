import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx


@dataclass
class FourOverConfig:
    base_url: str
    apikey: str
    private_key: str


def _get_fourover_config() -> FourOverConfig:
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
    apikey = os.getenv("FOUR_OVER_APIKEY")
    private_key = os.getenv("FOUR_OVER_PRIVATE_KEY")

    if not apikey:
        raise RuntimeError("FOUR_OVER_APIKEY is not set")
    if not private_key:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is not set")

    return FourOverConfig(base_url=base_url, apikey=apikey, private_key=private_key)


def _canonical_path_and_query(path: str, query: Dict[str, Any]) -> str:
    """
    4over debug in your past logs showed canonical like:
      /whoami?apikey=catdi
    We'll build query in stable sorted order.
    """
    # Always include apikey in query (some endpoints require it in query)
    items = sorted((k, str(v)) for k, v in query.items())
    qs = urlencode(items)
    return f"{path}?{qs}" if qs else path


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sign_variants(canonical: str, private_key: str) -> Dict[str, str]:
    """
    Try a few common signature strategies:
    - sha256(private_key + canonical)
    - sha256(canonical + private_key)
    - hmac_sha256(private_key, canonical)

    We'll send one at a time so you can see which (if any) works.
    """
    pk = private_key.encode("utf-8")
    can = canonical.encode("utf-8")

    return {
        "sha256_pk_plus_can": _sha256_hex(pk + can),
        "sha256_can_plus_pk": _sha256_hex(can + pk),
        "hmac_sha256_pk": hmac.new(pk, can, hashlib.sha256).hexdigest(),
    }


async def call_4over(
    path: str,
    extra_query: Optional[Dict[str, Any]] = None,
    timeout_s: float = 30.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Calls a 4over endpoint with apikey + signature in querystring (based on your earlier debug logs).
    Returns: (result_json_or_error, debug_info)
    """
    cfg = _get_fourover_config()

    query = {"apikey": cfg.apikey}
    if extra_query:
        query.update(extra_query)

    canonical = _canonical_path_and_query(path, query)
    signatures = _sign_variants(canonical, cfg.private_key)

    # Try each signature variant until one works
    last_error: Optional[Dict[str, Any]] = None

    async with httpx.AsyncClient(base_url=cfg.base_url, timeout=timeout_s) as client:
        for method_name, sig in signatures.items():
            query_with_sig = dict(query)
            query_with_sig["signature"] = sig

            url = f"{path}?{urlencode(sorted((k, str(v)) for k, v in query_with_sig.items()))}"

            try:
                resp = await client.get(url)
                content_type = resp.headers.get("content-type", "")

                # attempt json, fallback to text
                if "application/json" in content_type.lower():
                    data = resp.json()
                else:
                    data = {"raw": resp.text}

                # 2xx = success; some APIs return ok:false inside 200
                if 200 <= resp.status_code < 300:
                    return data, {
                        "base_url": cfg.base_url,
                        "path": path,
                        "canonical": canonical,
                        "signature_method": method_name,
                        "http_status": resp.status_code,
                    }

                last_error = {
                    "http_status": resp.status_code,
                    "data": data,
                    "signature_method": method_name,
                    "canonical": canonical,
                }
            except Exception as e:
                last_error = {
                    "exception": f"{type(e).__name__}: {e}",
                    "signature_method": method_name,
                    "canonical": canonical,
                }

    return (
        {
            "ok": False,
            "message": "All signature variants failed",
            "last_error": last_error,
        },
        {
            "base_url": cfg.base_url,
            "path": path,
            "canonical": canonical,
            "attempted_methods": list(signatures.keys()),
        },
    )
