from __future__ import annotations

import hashlib
import hmac
from typing import Iterable, Mapping, Sequence, Tuple, Union
from urllib.parse import quote, urlencode

import requests

from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY


class FourOverError(RuntimeError):
    def __init__(self, status: int, url: str, body: str, canonical: str):
        super().__init__(f"4over request failed ({status})")
        self.status = status
        self.url = url
        self.body = body
        self.canonical = canonical


def _require_keys() -> None:
    if not FOUR_OVER_BASE_URL:
        raise RuntimeError("FOUR_OVER_BASE_URL is missing")
    if not FOUR_OVER_APIKEY:
        raise RuntimeError("FOUR_OVER_APIKEY is missing")
    if not FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing")


QueryParams = Union[
    Mapping[str, object],
    Sequence[Tuple[str, object]],
]


def _normalize_params(params: QueryParams) -> list[tuple[str, str]]:
    """Normalize params into a list of (key, value_str) pairs.

    Important: we support repeated keys (e.g. ``options[]``) by allowing callers
    to pass a list of tuples.
    """
    items: list[tuple[str, str]] = []
    if isinstance(params, Mapping):
        for k, v in params.items():
            if v is None:
                continue
            items.append((str(k), str(v)))
    else:
        for k, v in params:
            if v is None:
                continue
            items.append((str(k), str(v)))
    return items


def _canonical_query(params: QueryParams, *, sort: bool = True) -> str:
    """Encode query params deterministically.

    - Uses RFC3986-ish encoding (spaces become %20, not '+') via ``quote``.
    - Supports repeated keys via list-of-tuples input.

    NOTE: Sorting is typically required for signature reproducibility. If 4over
    expects the *original order* for a specific endpoint, pass ``sort=False``
    with an already-ordered list-of-tuples.
    """
    items = _normalize_params(params)
    if sort:
        items = sorted(items, key=lambda kv: (kv[0], kv[1]))
    return urlencode(items, doseq=True, quote_via=quote, safe="")


def signature_for_canonical(canonical: str) -> str:
    """
    Canonical signing approach:
      signature = HMAC_SHA256(canonical, private_key)
    (canonical includes path + querystring WITHOUT signature param)
    """
    # Railway env vars can include trailing newlines when pasted.
    key = (FOUR_OVER_PRIVATE_KEY or "").strip().encode("utf-8")
    msg = canonical.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class FourOverClient:
    def __init__(self, base_url: str = FOUR_OVER_BASE_URL):
        _require_keys()
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, params: QueryParams | None = None, timeout: int = 30) -> dict:
        params = params or {}

        # Build canonical params excluding signature.
        # IMPORTANT: allow repeated keys by supporting list-of-tuples.
        if isinstance(params, Mapping):
            q_no_sig: QueryParams = {"apikey": FOUR_OVER_APIKEY, **params}
        else:
            q_no_sig = [("apikey", FOUR_OVER_APIKEY), *list(params)]

        canonical = f"{path}?{_canonical_query(q_no_sig)}"
        sig = signature_for_canonical(canonical)

        # Final URL includes signature
        if isinstance(q_no_sig, Mapping):
            q_with_sig: QueryParams = {**q_no_sig, "signature": sig}
        else:
            q_with_sig = [*list(q_no_sig), ("signature", sig)]

        url = f"{self.base_url}{path}?{_canonical_query(q_with_sig)}"

        r = requests.request(method.upper(), url, timeout=timeout)
        if r.status_code >= 400:
            raise FourOverError(r.status_code, url, r.text, canonical)

        # Some endpoints can return non-json; guard it
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    def whoami(self) -> dict:
        return self.request("GET", "/whoami")

    def product_baseprices(self, product_uuid: str) -> dict:
        return self.request("GET", f"/printproducts/products/{product_uuid}/baseprices")

    def product_optiongroups(self, product_uuid: str) -> dict:
        return self.request("GET", f"/printproducts/products/{product_uuid}/optiongroups")
