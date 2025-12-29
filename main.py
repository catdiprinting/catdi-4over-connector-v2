import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import engine, Base
from models import Ping
from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "0.7"
BUILD = "auth-locked-debug-sign-products-page"

app = FastAPI(title=APP_NAME)

# Create tables on boot (simple + safe for this phase)
Base.metadata.create_all(bind=engine)


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "db": "up"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "db": "down", "error": str(e)})


@app.get("/routes")
def routes():
    return {
        "routes": [
            "GET /",
            "GET /health",
            "GET /health/db",
            "GET /routes",
            "GET /version",
            "GET /debug/sign",
            "GET /4over/whoami",
            "GET /4over/products/page",
        ]
    }


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


def client() -> FourOverClient:
    try:
        return FourOverClient()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FourOverClient init failed: {str(e)}")


@app.get("/debug/sign")
def debug_sign(
    path: str = Query("/whoami", description="API path, e.g. /whoami or /products"),
    method: str = Query("GET", description="HTTP method, usually GET"),
):
    """
    Returns canonical string + signature for quick diffing.
    Never returns full private key.
    """
    c = client()
    signed_params, canonical, signature = c.debug_sign(method=method, path=path, params={})

    return {
        "ok": True,
        "method": method.upper(),
        "path": path,
        "canonical": canonical,
        "signature": signature,
        "params": {
            **{k: v for k, v in signed_params.items() if k not in ("apikey", "signature")},
            "apikey": mask(signed_params.get("apikey", "")),
            "signature": signature,
        },
        "env": {
            "base_url": os.getenv("FOUR_OVER_BASE_URL", "").rstrip("/"),
            "apikey_masked": mask(os.getenv("FOUR_OVER_APIKEY", "")),
            "private_key_len": len((os.getenv("FOUR_OVER_PRIVATE_KEY", "") or "")),
            "private_key_last4": mask((os.getenv("FOUR_OVER_PRIVATE_KEY", "") or "")[-4:], keep=4),
        },
    }


@app.get("/4over/whoami")
def four_over_whoami():
    c = client()
    resp, dbg = c.request("GET", "/whoami", params={})

    # Pass through the upstream response
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return {
        "ok": resp.ok,
        "http_status": resp.status_code,
        "data": data if resp.ok else None,
        "error": None if resp.ok else data,
        "debug": dbg if not resp.ok else None,
    }


@app.get("/4over/products/page")
def four_over_products_page(
    page: int = Query(1, ge=1, le=100000),
    per_page: int = Query(200, ge=10, le=500),
):
    """
    Safe ONE-PAGE pull from /products.

    NOTE: 4over paging params vary by endpoint/version.
    We support common patterns:
      - page / perPage
      - offset / limit
    If your /products expects a different scheme, we’ll adjust after we see the raw response.
    """
    c = client()

    # Try the most common first: page + perPage
    params = {"page": page, "perPage": per_page}

    resp, dbg = c.request("GET", "/products", params=params)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return {
        "ok": resp.ok,
        "http_status": resp.status_code,
        "request": {
            "path": "/products",
            "params": params,
        },
        "data": data if resp.ok else None,
        "error": None if resp.ok else data,
        "debug": dbg if not resp.ok else None,
    }
