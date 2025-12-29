import os
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import engine, Base
from models import Ping  # ensures model is registered
from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "0.8"
BUILD = "boot-safe-no-createall"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(APP_NAME)

app = FastAPI(title=APP_NAME)


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


@app.on_event("startup")
def startup():
    # Do NOT hard-fail boot if DB is down.
    # This prevents Railway "failed to respond".
    log.info("Starting %s phase=%s build=%s", APP_NAME, PHASE, BUILD)
    log.info("BASE_URL=%s", (os.getenv("FOUR_OVER_BASE_URL", "") or "").rstrip("/"))
    log.info("APIKEY=%s", mask(os.getenv("FOUR_OVER_APIKEY", "")))
    pk = os.getenv("FOUR_OVER_PRIVATE_KEY", "") or ""
    log.info("PRIVATE_KEY_LEN=%s", len(pk))

    # Optional DB sanity check (non-fatal)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("DB connectivity: OK")
    except Exception as e:
        log.warning("DB connectivity: FAILED (non-fatal). Error: %s", str(e))


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


@app.get("/db/init")
def db_init():
    """
    Explicit DB init endpoint.
    Use this ONLY when you want to create tables.
    Keeps Railway boot stable even if DB is slow.
    """
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True, "message": "DB tables created/verified"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/routes")
def routes():
    return {
        "routes": [
            "GET /",
            "GET /health",
            "GET /health/db",
            "GET /db/init",
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
    c = client()
    signed_params, canonical, signature = c.debug_sign(method=method, path=path, params={})
    return {
        "ok": True,
        "method": method.upper(),
        "path": path,
        "canonical": canonical,
        "signature": signature,
        "env": {
            "base_url": (os.getenv("FOUR_OVER_BASE_URL", "") or "").rstrip("/"),
            "apikey_masked": mask(os.getenv("FOUR_OVER_APIKEY", "")),
            "private_key_len": len((os.getenv("FOUR_OVER_PRIVATE_KEY", "") or "")),
        },
    }


@app.get("/4over/whoami")
def four_over_whoami():
    c = client()
    resp, dbg = c.request("GET", "/whoami", params={})
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
    c = client()
    params = {"page": page, "perPage": per_page}
    resp, dbg = c.request("GET", "/products", params=params)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return {
        "ok": resp.ok,
        "http_status": resp.status_code,
        "request": {"path": "/products", "params": params},
        "data": data if resp.ok else None,
        "error": None if resp.ok else data,
        "debug": dbg if not resp.ok else None,
    }
