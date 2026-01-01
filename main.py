# main.py
from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fourover_client import FourOverClient, FourOverError, FourOverAuthError, from_env

app = FastAPI(title="catdi-4over-connector", version="root-layout")

client: FourOverClient | None = None


@app.on_event("startup")
def startup() -> None:
    global client
    client = from_env()


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "root-layout"}


@app.get("/debug/auth")
def debug_auth():
    # Never leak keys. Just show presence + lengths.
    pk = os.getenv("FOUR_OVER_APIKEY", "")
    sk = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

    pk_present = bool(pk.strip())
    sk_present = bool(sk.strip())
    sk_raw = sk
    sk_strip = sk.strip()

    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").strip()

    return {
        "ok": True,
        "base_url": base_url,
        "apikey_present": pk_present,
        "private_key_present": sk_present,
        "private_key_len": len(sk_raw),
        "private_key_stripped_len": len(sk_strip),
        "private_key_endswith_newline": sk_raw.endswith("\n"),
        "note": "Signature is HMAC-SHA256(message=HTTP_METHOD, key=SHA256(private_key))",
    }


@app.get("/debug/sign")
def debug_sign():
    """
    Shows what signature we will use for GET requests.
    Per 4over docs, it is based on HTTP_METHOD only, not path/query.
    """
    if client is None:
        return JSONResponse({"ok": False, "error": "client_not_ready"}, status_code=500)

    return {
        "ok": True,
        "tests": [
            {
                "name": "GET signature",
                "method": "GET",
                "signature": client.signature_for_method("GET"),
            },
            {
                "name": "POST signature",
                "method": "POST",
                "signature": client.signature_for_method("POST"),
            },
        ],
    }


@app.get("/4over/whoami")
def fourover_whoami():
    if client is None:
        return JSONResponse({"ok": False, "error": "client_not_ready"}, status_code=500)

    try:
        data = client.whoami()
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(
            {
                "ok": False,
                "error": "4over_auth_failed",
                "status": 401,
                "detail": str(e)[:800],
            },
            status_code=401,
        )
    except FourOverError as e:
        return JSONResponse(
            {"ok": False, "error": "4over_error", "detail": str(e)[:1200]},
            status_code=500,
        )


@app.get("/4over/categories")
def fourover_categories(max: int = 1000, offset: int = 0):
    if client is None:
        return JSONResponse({"ok": False, "error": "client_not_ready"}, status_code=500)

    try:
        data = client.get_categories(max_=max, offset=offset)
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(
            {"ok": False, "error": "4over_auth_failed", "status": 401, "detail": str(e)[:800]},
            status_code=401,
        )
    except FourOverError as e:
        return JSONResponse(
            {"ok": False, "error": "4over_error", "detail": str(e)[:1200]},
            status_code=500,
        )


@app.get("/4over/categories/{category_uuid}/products")
def fourover_category_products(category_uuid: str, max: int = 1000, offset: int = 0):
    if client is None:
        return JSONResponse({"ok": False, "error": "client_not_ready"}, status_code=500)

    try:
        data = client.get_category_products(category_uuid=category_uuid, max_=max, offset=offset)
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(
            {"ok": False, "error": "4over_auth_failed", "status": 401, "detail": str(e)[:800]},
            status_code=401,
        )
    except FourOverError as e:
        return JSONResponse(
            {"ok": False, "error": "4over_error", "detail": str(e)[:1200]},
            status_code=500,
        )
