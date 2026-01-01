# fourover_client.py
"""
4over API Client — Standard Library Only (NO requests)

Auth scheme (per 4over docs you've been using in this project):
- GET / DELETE: include apikey + signature in query string
- POST / PUT / PATCH: include Authorization header: "API {apikey}:{signature}"
- Signature algorithm:
    signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))

Why this file exists:
- Your Railway deploys have crashed due to missing deps / import mismatches.
- This file avoids external deps and provides backward-compatible exports:
    - FourOverClient
    - client (singleton, safe)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


QueryParams = Union[
    Dict[str, Any],
    Sequence[Tuple[str, Any]],  # allows repeated keys: [("options[]","a"), ("options[]","b")]
]


class FourOverAuthError(RuntimeError):
    """Raised for 401 Unauthorized responses from 4over."""
    pass


class FourOverRequestError(RuntimeError):
    """Raised for request failures or non-2xx responses from 4over."""
    pass


def _normalize_private_key(raw: str) -> str:
    """
    Normalize private key from env vars:
    - Convert literal '\\n' into real newlines (for PEM stored in single-line env vars)
    - Strip whitespace
    """
    if raw is None:
        return ""
    return str(raw).replace("\\n", "\n").strip()


def _signature_for_method(http_method: str, private_key: str) -> str:
    """
    4over doc-style signature:
      signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))

    IMPORTANT DETAIL:
    Many doc examples do:
      key = sha256(private_key).hexdigest()
      signature = hmac_sha256(key, method)

    We'll match that: HMAC key is sha256(private_key).hexdigest() as UTF-8 bytes.
    """
    method = (http_method or "").upper().encode("utf-8")
    pk = _normalize_private_key(private_key)
    key = hashlib.sha256(pk.encode("utf-8")).hexdigest().encode("utf-8")
    return hmac.new(key, method, hashlib.sha256).hexdigest()


def _merge_params(base: Optional[QueryParams], extra: Optional[QueryParams]) -> QueryParams:
    """
    Merge query params while preserving repeated keys if either input is a list of tuples.
    """
    if base is None and extra is None:
        return {}
    if isinstance(base, (list, tuple)) or isinstance(extra, (list, tuple)):
        out: List[Tuple[str, Any]] = []
        if base is not None:
            if isinstance(base, (list, tuple)):
                out.extend(list(base))
            else:
                out.extend(list(base.items()))
        if extra is not None:
            if isinstance(extra, (list, tuple)):
                out.extend(list(extra))
            else:
                out.extend(list(extra.items()))
        return out
    merged = dict(base or {})
    merged.update(dict(extra or {}))
    return merged


def _params_to_query(params: Optional[QueryParams]) -> str:
    if not params:
        return ""
    if isinstance(params, (list, tuple)):
        return urlencode([(k, "" if v is None else str(v)) for k, v in params], doseq=True)
    return urlencode({k: "" if v is None else str(v) for k, v in params.items()}, doseq=True)


def _json_loads_safe(text: str) -> Any:
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:5000]}


@dataclass
class FourOverClientConfig:
    base_url: str
    apikey: str
    private_key: str
    timeout: int = 30
    user_agent: str = "catdi-4over-connector/1.0"


class FourOverClient:
    def __init__(self, config: FourOverClientConfig):
        self.base_url = (config.base_url or "").rstrip("/") + "/"
        self.apikey = (config.apikey or "").strip()
        self.private_key = config.private_key or ""
        self.timeout = int(config.timeout or 30)
        self.user_agent = config.user_agent or "catdi-4over-connector/1.0"

        if not self.base_url.strip("/"):
            raise ValueError("FOUR_OVER_BASE_URL is required")
        if not self.apikey:
            raise ValueError("FOUR_OVER_APIKEY is required")
        if not self.private_key:
            raise ValueError("FOUR_OVER_PRIVATE_KEY is required")

    @classmethod
    def from_env(cls) -> "FourOverClient":
        base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").strip()
        apikey = os.getenv("FOUR_OVER_APIKEY", "").strip()
        private_key = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
        timeout = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))
        return cls(
            FourOverClientConfig(
                base_url=base_url,
                apikey=apikey,
                private_key=private_key,
                timeout=timeout,
            )
        )

    # -------------------------
    # Core request
    # -------------------------
    def request(
        self,
        method: str,
        path: str,
        params: Optional[QueryParams] = None,
        json_body: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Returns a dict:
          {
            "status": int,
            "url": str,
            "headers": dict,
            "text": str,
            "json": parsed_json_or_none,
          }
        """
        method = (method or "GET").upper()
        if not path.startswith("/"):
            path = "/" + path

        # Build URL
        url = urljoin(self.base_url, path.lstrip("/"))

        # Build signature (method-based)
        sig = _signature_for_method(method, self.private_key)

        # Auth placement
        req_headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if headers:
            req_headers.update(headers)

        final_params: Optional[QueryParams] = params

        if method in ("GET", "DELETE"):
            auth_params: QueryParams = {"apikey": self.apikey, "signature": sig}
            final_params = _merge_params(params, auth_params)
        else:
            # POST/PUT/PATCH: auth in header
            req_headers["Authorization"] = f"API {self.apikey}:{sig}"

        qs = _params_to_query(final_params)
        if qs:
            full_url = f"{url}?{qs}"
        else:
            full_url = url

        data_bytes: Optional[bytes] = None
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        req = Request(full_url, data=data_bytes, headers=req_headers, method=method)

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200)
                out_headers = dict(resp.headers.items())
                return {
                    "status": status,
                    "url": full_url,
                    "headers": out_headers,
                    "text": text,
                    "json": _json_loads_safe(text),
                }

        except HTTPError as e:
            raw = e.read() if hasattr(e, "read") else b""
            text = raw.decode("utf-8", errors="replace") if raw else (str(e) or "")
            status = getattr(e, "code", 0) or 0
            body = _json_loads_safe(text)

            if status == 401:
                raise FourOverAuthError(
                    json.dumps(
                        {
                            "error": "4over_auth_failed",
                            "status": status,
                            "url": full_url,
                            "body": body,
                        }
                    )
                )

            raise FourOverRequestError(
                json.dumps(
                    {
                        "error": "4over_request_failed",
                        "status": status,
                        "url": full_url,
                        "body": body,
                    }
                )
            )

        except (URLError, socket.timeout) as e:
            raise FourOverRequestError(
                json.dumps(
                    {
                        "error": "4over_transport_failed",
                        "url": full_url,
                        "message": str(e),
                    }
                )
            )

    # -------------------------
    # Convenience JSON helpers
    # -------------------------
    def get_json(self, path: str, params: Optional[QueryParams] = None) -> Any:
        r = self.request("GET", path, params=params)
        return r["json"]

    def post_json(self, path: str, json_body: Any = None, params: Optional[QueryParams] = None) -> Any:
        r = self.request("POST", path, params=params, json_body=json_body)
        return r["json"]

    def delete_json(self, path: str, params: Optional[QueryParams] = None) -> Any:
        r = self.request("DELETE", path, params=params)
        return r["json"]

    # -------------------------
    # Pagination helper (max/offset)
    # -------------------------
    def paged_get_entities(
        self,
        path: str,
        base_params: Optional[Dict[str, Any]] = None,
        *,
        max_per_page: int = 1000,
        start_offset: int = 0,
        max_pages: int = 10000,
        entities_key: str = "entities",
    ) -> List[Any]:
        """
        Pages through 4over endpoints using max/offset.
        Assumes response is a dict containing entities_key (default "entities") list.
        """
        all_items: List[Any] = []
        offset = start_offset
        pages = 0
        base_params = dict(base_params or {})

        while True:
            pages += 1
            if pages > max_pages:
                raise FourOverRequestError(
                    f"Pagination exceeded max_pages={max_pages} for {path}"
                )

            params = dict(base_params)
            params["max"] = max_per_page
            params["offset"] = offset

            data = self.get_json(path, params=params)
            if not isinstance(data, dict):
                raise FourOverRequestError(f"Unexpected payload type for {path}: {type(data)}")

            entities = data.get(entities_key, [])
            if not isinstance(entities, list):
                raise FourOverRequestError(
                    f"Unexpected pagination key '{entities_key}' for {path}"
                )

            all_items.extend(entities)

            if len(entities) < max_per_page:
                break

            offset += max_per_page

        return all_items

    # -------------------------
    # Debug helpers (safe)
    # -------------------------
    def debug_signatures(self) -> Dict[str, str]:
        """
        Return signatures per method (no secrets).
        Useful for /debug/sign endpoints.
        """
        return {
            "GET": _signature_for_method("GET", self.private_key),
            "POST": _signature_for_method("POST", self.private_key),
            "PUT": _signature_for_method("PUT", self.private_key),
            "PATCH": _signature_for_method("PATCH", self.private_key),
            "DELETE": _signature_for_method("DELETE", self.private_key),
        }


# -------------------------------------------------------------------
# Backwards-compatible export: some older routers import `client`
# -------------------------------------------------------------------
try:
    client = FourOverClient.from_env()
except Exception:
    # Do not crash at import time (Railway 502). Routes can instantiate later.
    client = None
