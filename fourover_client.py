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


def _cfg() -> FourOverConfig:
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
    apikey = os.getenv("FOUR_OVER_APIKEY")
    private_key = os.getenv("FOUR_OVER_PRIVATE_KEY")

    if not apikey:
        raise RuntimeError("FOUR_OVER_APIKEY is not set (set this on the CONNECTOR service)")
    if not private_key:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is not set (set this on the CONNECTOR service)")

    return FourOverConfig(base_url=base_url, apikey=apikey, private_key=private_key)


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _hmac_sha256_hex(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _sorted_qs(params: Dict[str, Any]) -> str:
    return urlencode(sorted((k, str(v)) for k, v in params.items()))


def _candidate_canonicals(method: str, path: str, qs_no_sig: str, host: str) -> Dict[str, str]:
    """
    Try a handful of canonical forms that APIs commonly use.
    """
    # path must start with /
    if not path.startswith("/"):
        path = "/" + path

    candidates = {
        # what we already tried
        "path+qs": f"{path}?{qs_no_sig}" if qs_no_sig else path,
        # no leading slash
        "noslash_path+qs": f"{path.lstrip('/')}?{qs_no_sig}" if qs_no_sig else path.lstrip("/"),
        # method included
        "method\\npath+qs": f"{method.upper()}\n{path}?{qs_no_sig}" if qs_no_sig else f"{method.upper()}\n{path}",
        # method + path only (no qs)
        "method\\npath": f"{method.upper()}\n{path}",
        # host included
        "host+path+qs": f"{host}{path}?{qs_no_sig}" if qs_no_sig else f"{host}{path}",
        # full URL
        "full_url": f"https://{host}{path}?{qs_no_sig}" if qs_no_sig else f"https://{host}{path}",
    }
    return candidates


def _signature_methods(private_key: str, canonical: str) -> Dict[str, str]:
    pk = private_key.encode("utf-8")
    can = canonical.encode("utf-8")

    return {
        "sha256(pk+can)": _sha256_hex(pk + can),
        "sha256(can+pk)": _sha256_hex(can + pk),
        "hmac(pk,can)": _hmac_sha256_hex(pk, can),
        # sometimes key must be sha256(key) first
        "hmac(sha256(pk),can)": _hmac_sha256_hex(hashlib.sha256(pk).digest(), can),
    }


async def call_4over_probe(
    path: str,
    method: str = "GET",
    extra_query: Optional[Dict[str, Any]] = None,
    timeout_s: float = 30.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Probes multiple canonical + signature + placement strategies.
    Returns (result, debug) where result includes ok:false on failure.
    """
    cfg = _cfg()

    # Base query (no signature)
    query = {"apikey": cfg.apikey}
    if extra_query:
        query.update(extra_query)

    qs_no_sig = _sorted_qs(query)
    host = cfg.base_url.replace("https://", "").replace("http://", "").split("/")[0]

    canonicals = _candidate_canonicals(method=method, path=path, qs_no_sig=qs_no_sig, host=host)

    async with httpx.AsyncClient(base_url=cfg.base_url, timeout=timeout_s) as client:
        last_error: Dict[str, Any] = {}

        for canon_name, canonical in canonicals.items():
            sigs = _signature_methods(cfg.private_key, canonical)

            for sig_name, sig in sigs.items():
                # Strategy A: signature in query string (what you were originally doing)
                q1 = dict(query)
                q1["signature"] = sig
                url_q = f"{path}?{_sorted_qs(q1)}"

                # Strategy B: signature in headers (common alternate pattern)
                headers = {
                    "X-APIKEY": cfg.apikey,
                    "X-SIGNATURE": sig,
                }

                # Try both placements
                for placement, req in [
                    ("query", {"url": url_q, "headers": {}}),
                    ("headers", {"url": f"{path}?{qs_no_sig}" if qs_no_sig else path, "headers": headers}),
                ]:
                    try:
                        resp = await client.request(method.upper(), req["url"], headers=req["headers"])
                        ct = (resp.headers.get("content-type") or "").lower()
                        data = resp.json() if "application/json" in ct else {"raw": resp.text}

                        if 200 <= resp.status_code < 300 and not (isinstance(data, dict) and data.get("status") == "error"):
                            return data, {
                                "base_url": cfg.base_url,
                                "path": path,
                                "method": method.upper(),
                                "canonical_used": canonical,
                                "canonical_variant": canon_name,
                                "signature_variant": sig_name,
                                "placement": placement,
                                "http_status": resp.status_code,
                            }

                        last_error = {
                            "http_status": resp.status_code,
                            "data": data,
                            "canonical_variant": canon_name,
                            "signature_variant": sig_name,
                            "placement": placement,
                            "canonical_used": canonical,
                        }
                    except Exception as e:
                        last_error = {
                            "exception": f"{type(e).__name__}: {e}",
                            "canonical_variant": canon_name,
                            "signature_variant": sig_name,
                            "placement": placement,
                            "canonical_used": canonical,
                        }

        return {
            "ok": False,
            "message": "Probe failed: no canonical/signature/placement combo succeeded",
            "last_error": last_error,
        }, {
            "base_url": cfg.base_url,
            "path": path,
            "method": method.upper(),
            "attempted_canonicals": list(canonicals.keys()),
            "attempted_signature_variants": ["sha256(pk+can)", "sha256(can+pk)", "hmac(pk,can)", "hmac(sha256(pk),can)"],
            "attempted_placements": ["query", "headers"],
        }
