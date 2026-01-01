# fourover_client.py
"""
4over API Client (Doc-Style Authentication)

Per 4over docs:
- GET/DELETE: send apikey + signature as query params
- POST/PUT/PATCH: send Authorization header: "API {apikey}:{signature}"
- Signature algorithm: HMAC-SHA256(message=HTTP_METHOD, key=SHA256(private_key))

This file is intentionally "boring + reliable":
- No signing of path/query/body
- Supports pagination via max/offset
- Supports repeated query params if you pass params as a list of tuples
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlencode

import requests


QueryParams = Union[
    Dict[str, Any],
    Sequence[Tuple[str, Any]],  # allows repeated keys like ("options[]", "uuid1"), ("options[]", "uuid2")
]


class FourOverAuthError(RuntimeError):
    pass


class FourOverRequestError(RuntimeError):
    pass


def _normalize_private_key(raw: str) -> str:
    """
    Normalize private key from env vars:
    - Convert literal '\\n' into newlines (for PEM-style secrets stored in single-line env vars)
    - Strip whitespace
    """
    if raw is None:
        return ""
    return str(raw).replace("\\n", "\n").strip()


def _signature_for_method(http_method: str, private_key: str) -> str:
    """
    4over doc-style signature:
    signature = HMAC_SHA256(message=HTTP_METHOD, key=SHA256(private_key))

    NOTE: the HMAC key is the hex digest of sha256(private_key), encoded as UTF-8 bytes,
    matching the style shown in many docs/examples.
    """
    m = (http_method or "").upper().encode("utf-8")
    pk = _normalize_private_key(private_key)
    key = hashlib.sha256(pk.encode("utf-8")).hexdigest().encode("utf-8")
    return hmac.new(key, m, hashlib.sha256).hexdigest()


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
    # both dicts
    merged = dict(base or {})
    merged.update(dict(extra or {}))
    return merged


def _params_to_querystring(params: Optional[QueryParams]) -> str:
    if not params:
        return ""
    if isinstance(params, (list, tuple)):
        return urlencode([(k, "" if v is None else str(v)) for k, v in params], doseq=True)
    return urlencode({k: "" if v is None else str(v) for k, v in params.items()}, doseq=True)


@dataclass
class FourOverClientConfig:
    base_url: str
    apikey: str
    private_key: str
    timeout: int = 30
    user_agent: str = "catdi-4over-connector/1.0"


class FourOverClient:
    def __init__(self, config: FourOverClientConfig):
        self.base_url = (config.base_url or "").rstrip("/")
        self.apikey = (config.apikey or "").strip()
        self.private_key = config.private_key or ""
        self.timeout = config.timeout
        self.user_agent = config.user_agent

        if not self.base_url:
            raise ValueError("FourOverClient base_url is required")
        if not self.apikey:
            raise ValueError("FourOverClient apikey is required")
        if not self.private_key:
            raise ValueError("FourOverClient private_key is required")

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
    ) -> requests.Response:
        method = (method or "").upper()
        if not path.startswith("/"):
            path = "/" + path

        url = f"{self.base_url}{path}"

        sig = _signature_for_method(method, self.private_key)

        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }

        # Auth placement per docs
        if method in ("GET", "DELETE"):
            auth_params: QueryParams = {"apikey": self.apikey, "signature": sig}
            merged = _merge_params(params, auth_params)
            final_params = merged
        else:
            headers["Authorization"] = f"API {self.apikey}:{sig}"
            final_params = params

        try:
            resp = requests.request(
                method,
                url,
                params=final_params if final_params else None,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise FourOverRequestError(f"Request failed: {method} {url} -> {e}") from e

        # Raise for auth specifically
        if resp.status_code == 401:
            raise FourOverAuthError(
                f"4over Authentication Failed (401) for {method} {url} "
                f"params={_params_to_querystring(final_params)}"
            )

        return resp

    # -------------------------
    # Helpers that return JSON
    # -------------------------
    def get_json(self, path: str, params: Optional[QueryParams] = None) -> Any:
        resp = self.request("GET", path, params=params)
        return self._parse_json_or_raise(resp)

    def post_json(self, path: str, json_body: Any = None, params: Optional[QueryParams] = None) -> Any:
        resp = self.request("POST", path, params=params, json_body=json_body)
        return self._parse_json_or_raise(resp)

    def delete_json(self, path: str, params: Optional[QueryParams] = None) -> Any:
        resp = self.request("DELETE", path, params=params)
        return self._parse_json_or_raise(resp)

    def _parse_json_or_raise(self, resp: requests.Response) -> Any:
        """
        Normalize errors into useful exceptions. 4over often returns JSON error bodies.
        """
        text = resp.text or ""
        if resp.status_code >= 400:
            # attempt to parse body for message
            try:
                body = resp.json()
            except Exception:
                body = {"raw": text[:2000]}
            raise FourOverRequestError(
                f"4over_request_failed status={resp.status_code} url={resp.url} body={body}"
            )

        if not text.strip():
            return None

        try:
            return resp.json()
        except Exception as e:
            raise FourOverRequestError(f"Expected JSON but got non-JSON from {resp.url}: {text[:2000]}") from e

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
        Many 4over endpoints return { "entities": [...], ... } and default to 20 items.
        This helper pages using max/offset until the returned entity count < max.

        - entities_key defaults to "entities" but can be changed if needed.
        """
        all_entities: List[Any] = []
        offset = start_offset
        pages = 0
        base_params = dict(base_params or {})

        while True:
            pages += 1
            if pages > max_pages:
                raise FourOverRequestError(f"Pagination exceeded max_pages={max_pages} for {path}")

            params = dict(base_params)
            params["max"] = max_per_page
            params["offset"] = offset

            data = self.get_json(path, params=params)
            entities = data.get(entities_key, []) if isinstance(data, dict) else []

            if not isinstance(entities, list):
                raise FourOverRequestError(
                    f"Unexpected pagination payload for {path}: expected list at key '{entities_key}'"
                )

            all_entities.extend(entities)

            # stop condition
            if len(entities) < max_per_page:
                break

            offset += max_per_page

        return all_entities

    # -------------------------
    # Debug helpers (safe)
    # -------------------------
    def debug_signatures(self) -> Dict[str, str]:
        """
        Returns the signatures this client will generate per method (no secrets exposed).
        """
        return {
            "GET": _signature_for_method("GET", self.private_key),
            "POST": _signature_for_method("POST", self.private_key),
            "PUT": _signature_for_method("PUT", self.private_key),
            "PATCH": _signature_for_method("PATCH", self.private_key),
            "DELETE": _signature_for_method("DELETE", self.private_key),
        }
# Backwards-compatible singleton (older routers import `client`)
try:
    client = FourOverClient.from_env()
except Exception:
    # Avoid crashing at import time; routes can instantiate later if needed
    client = None
