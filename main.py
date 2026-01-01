from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, whoami, product_baseprices
from db import ensure_schema
from doorhangers import router as doorhangers_router

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")
app.include_router(doorhangers_router)


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    return {"ok": True}


@app.post("/db/init")
def db_init():
    """
    Idempotent schema init / migration.
    Must NEVER crash the app.
    """
    try:
        ensure_schema()
        return {"ok": True, "tables": ["baseprice_cache"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


@app.get("/4over/whoami")
def four_over_whoami():
    try:
        return whoami()
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": getattr(e, "canonical", None),
                }
            },
        )


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    """
    Debug endpoint: fetch baseprices live from 4over (no DB).
    """
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": getattr(e, "canonical", None),
                }
            },
        )
