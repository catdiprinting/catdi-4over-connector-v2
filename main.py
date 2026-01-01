# main.py
import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fourover_client import FourOverClient, FourOverError, FourOverAuthError

app = FastAPI(title="catdi-4over-connector", version="root-layout")

def _client() -> FourOverClient:
    return FourOverClient(
        base_url=os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        public_key=os.getenv("FOUR_OVER_APIKEY", ""),
        private_key=os.getenv("FOUR_OVER_PRIVATE_KEY", ""),
        timeout=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
    )

@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "root-layout"}

@app.get("/debug/auth")
def debug_auth():
    pk = os.getenv("FOUR_OVER_APIKEY", "")
    sk = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
    base = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
    return {
        "ok": True,
        "base_url": base,
        "apikey_present": bool(pk),
        "private_key_present": bool(sk),
        "private_key_len": len(sk),
        "private_key_endswith_newline": sk.endswith("\n"),
        "note": "Per 4over docs: signature = HMAC-SHA256(HTTP_METHOD, sha256(private_key).hexdigest())",
    }

@app.get("/debug/sign")
def debug_sign():
    # show method-only signatures (what 4over expects)
    try:
        c = _client()
        # Access internal helper safely
        get_sig = c._signature_for_method("GET")
        post_sig = c._signature_for_method("POST")
        return {
            "ok": True,
            "tests": [
                {"name": "GET signature", "method": "GET", "signature": get_sig},
                {"name": "POST signature", "method": "POST", "signature": post_sig},
            ],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "debug_sign_failed", "detail": str(e)})

@app.get("/4over/whoami")
def whoami():
    try:
        c = _client()
        data = c.get("/whoami")
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": "4over_auth_failed", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "4over_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})

# Optional helper endpoint: categories with pagination
@app.get("/4over/categories")
def categories(max: int = 100, offset: int = 0):
    """
    4over defaults to max=20 offset=0 if not provided.
    Docs: https://api-users.4over.com/?page_id=24
    """
    try:
        c = _client()
        data = c.get("/printproducts/categories", params={"max": max, "offset": offset})
        return {"ok": True, "data": data, "max": max, "offset": offset}
    except FourOverAuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": "4over_auth_failed", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "4over_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})
