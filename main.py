# main.py
import time
import hashlib
import requests

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY, FOUR_OVER_BASE_URL, DEBUG
from db import engine, SessionLocal
from models import Base

APP_INFO = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_V4_SAFE_ERRORS",
}

app = FastAPI(title="Catdi 4over Connector")

# ---------- DB dependency ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- global error handler (prevents silent 500s) ----------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # If DEBUG=1, show a bit more info; otherwise keep it simple.
    detail = {"error": "Unhandled server error", "path": str(request.url.path)}
    if DEBUG:
        detail["exception"] = repr(exc)
    return JSONResponse(status_code=500, content={"detail": detail})

# ---------- health endpoints ----------
@app.get("/version")
def version():
    return APP_INFO

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/db/ping")
def db_ping():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}

@app.post("/db/init")
def db_init():
    """
    Creates tables + index safely.
    Uses SQLAlchemy for tables, and CREATE INDEX IF NOT EXISTS to avoid duplicates.
    """
    try:
        Base.metadata.create_all(bind=engine)

        with engine.begin() as conn:
            # Works on Postgres + SQLite
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid "
                "ON baseprice_cache (product_uuid)"
            ))

        return {"ok": True}
    except Exception as e:
        # Return useful info instead of crashing
        raise HTTPException(status_code=500, detail=f"DB init failed: {repr(e)}")

# ---------- 4over signing ----------
def sign_4over(canonical: str) -> str:
    """
    4over signature = SHA1(canonical + private_key) in hex.
    canonical example: "/whoami?apikey=catdi&timestamp=123"
    """
    if not FOUR_OVER_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="Missing env var: FOUR_OVER_PRIVATE_KEY")
    raw = (canonical + FOUR_OVER_PRIVATE_KEY).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()

def four_over_get(path: str, extra_params: dict | None = None) -> dict:
    if not FOUR_OVER_APIKEY:
        raise HTTPException(status_code=500, detail="Missing env var: FOUR_OVER_APIKEY")
    base = (FOUR_OVER_BASE_URL or "https://api.4over.com").rstrip("/")

    params = {"apikey": FOUR_OVER_APIKEY, "timestamp": str(int(time.time()))}
    if extra_params:
        params.update(extra_params)

    # Build canonical (must match query order we send)
    # We'll build query string ourselves to keep it deterministic.
    query = "&".join([f"{k}={params[k]}" for k in params.keys()])
    canonical = f"{path}?{query}"
    signature = sign_4over(canonical)
    params["signature"] = signature

    url = f"{base}{path}"

    try:
        r = requests.get(url, params=params, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "Request failed", "exception": repr(e), "url": url})

    # IMPORTANT: don't crash with raise_for_status(); return structured error
    if r.status_code >= 400:
        raise HTTPException(
            status_code=r.status_code,
            detail={
                "error": "4over request failed",
                "status": r.status_code,
                "url": r.url,
                "body": r.text[:1200],
                "canonical": canonical,
            },
        )

    return r.json()

# ---------- 4over endpoints ----------
@app.get("/4over/whoami")
def whoami():
    return four_over_get("/whoami")
