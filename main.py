import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "baseline"
BUILD = "boot-proof-no-db"


app = FastAPI(title=APP_NAME)


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def client() -> FourOverClient:
    try:
        return FourOverClient()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/env")
def env():
    return {
        "FOUR_OVER_BASE_URL": (os.getenv("FOUR_OVER_BASE_URL", "") or "").rstrip("/"),
        "FOUR_OVER_APIKEY_masked": mask(os.getenv("FOUR_OVER_APIKEY", "")),
        "FOUR_OVER_PRIVATE_KEY_len": len((os.getenv("FOUR_OVER_PRIVATE_KEY", "") or "")),
        "DATABASE_URL_present": bool(os.getenv("DATABASE_URL")),
    }


@app.get("/debug/sign")
def debug_sign(
    path: str = Query("/whoami"),
):
    c = client()
    # Build signature without calling upstream (safe)
    resp, dbg = c.get(path, params={})
    # We only need the canonical/signature; don't require upstream to be healthy
    return {"ok": True, "path": path, "canonical": dbg["canonical"], "signature": dbg["signature"]}


@app.get("/4over/whoami")
def whoami():
    c = client()
    resp, dbg = c.get("/whoami", params={})
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


@app.get("/4over/products")
def products(
    max: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000000),
):
    c = client()
    resp, dbg = c.get("/products", params={"max": max, "offset": offset})
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return {
        "ok": resp.ok,
        "http_status": resp.status_code,
        "request": {"max": max, "offset": offset},
        "data": data if resp.ok else None,
        "error": None if resp.ok else data,
        "debug": dbg if not resp.ok else None,
    }
