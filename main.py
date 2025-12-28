from fastapi import FastAPI
from fastapi.responses import JSONResponse
from typing import Dict, Any
import os

app = FastAPI(title="Catdi 4over Connector", version="0.7")

# -----------------------------------------------------------------------------
# Global exception handler (so you never see a useless 500 again)
# -----------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "http_status": 500,
            "error": str(exc),
            "path": str(request.url.path),
        },
    )

# -----------------------------------------------------------------------------
# Root / Health / Version / Fingerprint
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.7", "build": "4over-auth-locked"}


@app.get("/fingerprint")
def fingerprint():
    return {"fingerprint": "ROOT_MAIN_PY_V2", "file": "/app/main.py"}


# -----------------------------------------------------------------------------
# DB CHECK (lazy import)
# -----------------------------------------------------------------------------
@app.get("/db-check")
def db_check() -> Dict[str, Any]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {"db": "missing DATABASE_URL"}

    try:
        import psycopg2  # lazy import
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "error": str(e)}


# -----------------------------------------------------------------------------
# 4over helpers (safe import)
# -----------------------------------------------------------------------------
def _get_client():
    """
    Always returns a tuple:
      (client, None) on success
      (None, "error string") on failure
    """
    try:
        from fourover_client import FourOverClient
        return FourOverClient(), None
    except Exception as e:
        return None, str(e)


# -----------------------------------------------------------------------------
# 4over – AUTH TEST
# -----------------------------------------------------------------------------
@app.get("/4over/whoami")
def fourover_whoami():
    client, err = _get_client()
    if not client:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Failed to create FourOverClient"},
            "debug": {"error": err},
        }

    try:
        return client.request("GET", "/whoami")
    except Exception as e:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Exception during whoami"},
            "debug": {"error": str(e)},
        }


# -----------------------------------------------------------------------------
# 4over – CATALOG EXPLORER
# -----------------------------------------------------------------------------
@app.get("/4over/printproducts/categories")
def fourover_categories(max: int = 1000, offset: int = 0):
    client, err = _get_client()
    if not client:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Failed to create FourOverClient"},
            "debug": {"error": err},
        }

    try:
        return client.request("GET", "/printproducts/categories", params={"max": max, "offset": offset})
    except Exception as e:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Exception during categories call"},
            "debug": {"error": str(e), "max": max, "offset": offset},
        }


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def fourover_category_products(category_uuid: str, max: int = 1000, offset: int = 0):
    client, err = _get_client()
    if not client:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Failed to create FourOverClient"},
            "debug": {"error": err},
        }

    try:
        return client.request(
            "GET",
            f"/printproducts/categories/{category_uuid}/products",
            params={"max": max, "offset": offset},
        )
    except Exception as e:
        return {
            "ok": False,
            "http_status": 500,
            "data": {"message": "Exception during category products call"},
            "debug": {"error": str(e), "category_uuid": category_uuid, "max": max, "offset": offset},
        }
