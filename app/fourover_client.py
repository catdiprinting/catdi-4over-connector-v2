# app/fourover_client.py
import hmac
import hashlib
import requests
from urllib.parse import urlencode, quote


class FourOverClient:
    """
    Builds a *fully-signed URL* so the canonical string used for HMAC
    matches the exact query string sent over the wire.
    """

    def __init__(self, base_url: str, apikey: str, private_key: str, timeout: int = 30):
        self.base_url = (base_url or "").rstrip("/")
        self.apikey = (apikey or "").strip()
        # IMPORTANT: strip whitespace/newlines from copied secrets
        self.private_key = (private_key or "").strip()
        self.timeout = timeout

    def _sign(self, canonical: str) -> str:
        return hmac.new(
            self.private_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _normalize_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return path

    def _encode_qs(self, params: dict) -> str:
        """
        Use deterministic encoding:
        - sort by key
        - percent-encode consistently (not plus-space weirdness)
        """
        items = sorted((k, "" if v is None else str(v)) for k, v in params.items())
        # quote() makes spaces %20 instead of +
        return urlencode(items, quote_via=quote, safe="")

    def signed_url(self, path: str, params: dict | None = None) -> tuple[str, str]:
        """
        Returns (full_url, canonical_string_used_for_signature)
        """
        path = self._normalize_path(path)
        params = dict(params or {})
        params["apikey"] = self.apikey

        qs = self._encode_qs(params)
        canonical = f"{path}?{qs}" if qs else path

        sig = self._sign(canonical)

        # append signature as LAST param (keeps canonical clean & predictable)
        full_qs = qs + ("&" if qs else "") + f"signature={sig}"
        url = f"{self.base_url}{path}?{full_qs}"

        return url, canonical

    def get(self, path: str, params: dict | None = None) -> dict:
        url, canonical = self.signed_url(path, params)

        r = requests.get(url, timeout=self.timeout)
        try:
            data = r.json()
        except Exception:
            return {
                "status": "error",
                "http_code": r.status_code,
                "text": r.text,
                "debug": {"url": url, "canonical": canonical},
            }

        # Always attach debug when not 200
        if r.status_code >= 400:
            return {
                "status": "error",
                "http_code": r.status_code,
                "response": data,
                "debug": {"url": url, "canonical": canonical},
            }

        return data
