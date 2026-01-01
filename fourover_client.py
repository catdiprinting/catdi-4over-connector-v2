# fourover_client.py
import os
import json
import hmac
import hashlib
from typing import Any, Dict, Optional, Tuple, Union

import requests


class FourOverError(Exception):
    """Base error for 4over client."""


class FourOverAuthError(FourOverError):
    """Raised when 4over returns 401/403 or auth fails."""


class FourOverAPIError(FourOverError):
    """Raised for non-auth API errors."""


class FourOverClient:
    """
    4over API client implementing API Key Authentication per 4over docs.

    Key point:
    - Signature is HMAC-SHA256 of the HTTP_METHOD (e.g., "GET", "POST")
      using sha256(private_key) as the HMAC key.
    - For GET/DELETE: pass apikey + signature in query string.
    - For POST/PUT/PATCH: pass Authorization header: "API {PUBLIC_KEY}:{SIGNATURE}"

    Docs: https://api-users.4over.com/?page_id=44
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        public_key: Optional[str] = None,
        private_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (base_url or os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")).rstrip("/")
        self.public_key = public_key or os.getenv("FOUR_OVER_APIKEY", "")
        self.private_key = private_key or os.getenv("FOUR_OVER_PRIVATE_KEY", "")
        self.timeout = timeout

        if not self.public_key:
            raise FourOverAuthError("Missing FOUR_OVER_APIKEY (public key).")
        if not self.private_key:
            raise FourOverAuthError("Missing FOUR_OVER_PRIVATE_KEY (private key).")

        # Per docs: private_key = sha256(private_key).hexdigest()
        # Use that hex string (as bytes) as the HMAC key
        hashed = hashlib.sha256(self.private_key.encode("utf-8")).hexdigest()
        self._hmac_key = hashed.encode("utf-8")

        self._session = requests.Session()

    def _signature_for_method(self, method: str) -> str:
        m = method.upper().encode("utf-8")
        return hmac.new(self._hmac_key, m, hashlib.sha256).hexdigest()

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _parse_json(self, resp: requests.Response) -> Union[Dict[str, Any], Any, str]:
        ctype = (resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                return resp.json()
            except Exception:
                return resp.text
        # 4over sometimes returns JSON as text; try anyway
        try:
            return json.loads(resp.text)
        except Exception:
            return resp.text

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Union[Dict[str, Any], Any, str]]:
        method_u = method.upper()
        sig = self._signature_for_method(method_u)
        url = self._url(path)

        params = dict(params or {})
        hdrs: Dict[str, str] = {"accept": "application/json"}
        if headers:
            hdrs.update(headers)

        # Auth rules per docs
        if method_u in ("GET", "DELETE"):
            params["apikey"] = self.public_key
            params["signature"] = sig
        elif method_u in ("POST", "PUT", "PATCH"):
            hdrs["Authorization"] = f"API {self.public_key}:{sig}"
            hdrs.setdefault("content-type", "application/json")
        else:
            raise FourOverAPIError(f"Unsupported HTTP method: {method_u}")

        resp = self._session.request(
            method=method_u,
            url=url,
            params=params if params else None,
            json=json_body,
            headers=hdrs,
            timeout=self.timeout,
        )

        data = self._parse_json(resp)

        if resp.status_code in (401, 403):
            raise FourOverAuthError(
                f"4over auth failed ({resp.status_code}) for {method_u} {url}. Response: {data}"
            )

        if resp.status_code >= 400:
            raise FourOverAPIError(
                f"4over request failed ({resp.status_code}) for {method_u} {url}. Response: {data}"
            )

        return resp.status_code, data

    # Convenience wrappers
    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        _, data = self.request("GET", path, params=params)
        return data

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        _, data = self.request("DELETE", path, params=params)
        return data

    def post(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        _, data = self.request("POST", path, json_body=json_body)
        return data

    def put(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        _, data = self.request("PUT", path, json_body=json_body)
        return data

    def patch(self, path: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
        _, data = self.request("PATCH", path, json_body=json_body)
        return data
