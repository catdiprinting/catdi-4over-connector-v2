# main.py
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverClient, FourOverError, FourOverAuthError

app = FastAPI(title="catdi-4over-connector", version="0.1.0")


def _env_debug() -> Dict[str, Any]:
    apikey = os.getenv("FOUR_OVER_APIKEY")
    pkey = os.getenv("FOUR_OVER_PRIVATE_KEY")
    base = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")

    pkey_stripped = (pkey or "").strip()
    return {
        "ok": True,
        "base_url": base,
        "apikey_present": bool((apikey or "").strip()),
        "private_key_present": bool((pkey or "").strip()),
        "private_key_len": len(pkey or ""),
        "private_key_stripped_len": len(pkey_stripped),
        "private_key_endswith_newline": (pkey or "").endswith("\n"),
        "note": "Signature is canonical(path+sorted_query) HMAC-SHA256 with private key",
    }


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "root-layout"}


@app.get("/debug/auth")
def debug_auth():
    return _env_debug()


@app.get("/debug/sign")
def debug_sign(product_uuid: Optional[str] = Query(default=None)):
    """
    Returns canonical + signature examples without making external calls.
    """
    client = FourOverClient.from_env()

    tests = []
    canonical, sig = client.sign("/whoami", params={})
    tests.append({"name": "whoami", "canonical": canonical, "signature": sig})

    if product_uuid:
        canonical, sig = client.sign(
            f"/printproducts/products/{product_uuid}/baseprices", params={}
        )
        tests.append(
            {
                "name": f"/printproducts/products/{product_uuid}/baseprices",
                "canonical": canonical,
                "signature": sig,
            }
        )

        canonical, sig = client.sign(
            f"/printproducts/products/{product_uuid}/optiongroups", params={}
        )
        tests.append(
            {
                "name": f"/printproducts/products/{product_uuid}/optiongroups",
                "canonical": canonical,
                "signature": sig,
            }
        )

    return {"ok": True, "tests": tests}


@app.get("/4over/whoami")
def fourover_whoami():
    """
    Calls 4over /whoami via signed URL.
    """
    try:
        client = FourOverClient.from_env()
        data = client.whoami()
        return data
    except FourOverAuthError as e:
        # return the structured JSON string if possible
        try:
            return JSONResponse(status_code=401, content={"ok": False, **__import__("json").loads(str(e))})
        except Exception:
            return JSONResponse(status_code=401, content={"ok": False, "error": "auth_failed", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "client_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})
