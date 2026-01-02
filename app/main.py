from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from app.db import get_db, init_db
from app import models

app = FastAPI(title="catdi-4over-connector", version="1.0")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_client():
    # Lazy import + lazy init so app does not crash at startup
    from app.fourover_client import FourOverClient
    return FourOverClient()


@app.get("/debug/auth")
def debug_auth():
    """
    Must respond even if env is broken.
    """
    from app import config

    apikey = (config.FOUR_OVER_APIKEY or "").strip() if config.FOUR_OVER_APIKEY else ""
    pkey = (config.FOUR_OVER_PRIVATE_KEY or "").strip() if config.FOUR_OVER_PRIVATE_KEY else ""

    def safe_edge(s: str, n: int = 3) -> str:
        if not s:
            return ""
        if len(s) <= n * 2:
            return s
        return f"{s[:n]}...{s[-n:]}"

    out = {
        "base_url": (config.FOUR_OVER_BASE_URL or "").rstrip("/"),
        "api_prefix": (config.FOUR_OVER_API_PREFIX or "").strip("/"),
        "timeout": str(config.FOUR_OVER_TIMEOUT),
        "apikey_present": bool(apikey),
        "private_key_present": bool(pkey),
        "apikey_edge": safe_edge(apikey, 3),
        "private_key_len": len(pkey),
    }

    # Try to compute signatures; if this fails, return the error instead of crashing
    try:
        client = get_client()
        sig_get = client.signature_for_method("GET")
        sig_post = client.signature_for_method("POST")
        out.update({
            "sig_GET_edge": safe_edge(sig_get, 6),
            "sig_POST_edge": safe_edge(sig_post, 6),
            "note": "GET uses query auth; POST uses Authorization: API apikey:signature",
        })
    except Exception as e:
        out.update({
            "client_init_error": str(e),
            "note": "Client failed to init. Fix env vars in Railway.",
        })

    return out


# ----------------------------
# 4over passthrough endpoints
# ----------------------------

@app.get("/4over/whoami")
def whoami():
    try:
        client = get_client()
        r = client.get("/whoami")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Client/init error: {e}")

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories")
def categories(max: int = 50, offset: int = 0):
    client = get_client()
    r = client.get("/categories", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    client = get_client()
    r = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    client = get_client()
    r = client.get(f"/products/{product_uuid}")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = 200, offset: int = 0):
    client = get_client()
    r = client.get(f"/products/{product_uuid}/baseprices", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}
