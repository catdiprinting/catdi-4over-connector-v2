# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami
from db import (
    ensure_schema,
    insert_baseprice_cache,
    list_baseprice_cache,
    latest_baseprice_cache,
)

# If your /doorhangers/quote and /doorhangers/options endpoints live in doorhangers.py,
# this mounts them without changing any existing paths.
try:
    from doorhangers import router as doorhangers_router  # expects APIRouter() named "router"
except Exception:
    doorhangers_router = None

# Optional: if you have catalog routes in routes_catalog.py
try:
    from routes_catalog import router as catalog_router
except Exception:
    catalog_router = None

# Optional: pricing tester router if it exists as "router"
try:
    from pricing_tester import router as pricing_tester_router
except Exception:
    pricing_tester_router = None


APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


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
    try:
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "DB init failed", "message": str(e)},
        )


@app.get("/4over/whoami")
def four_over_whoami():
    try:
        return whoami()
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and cache into Postgres.
    """
    try:
        ensure_schema()  # idempotent migrations
        payload = product_baseprices(product_uuid)
        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "db error", "message": str(e)},
        )


@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        ensure_schema()
        return {"entities": list_baseprice_cache(limit=limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "cache list failed", "message": str(e)},
        )


@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    try:
        ensure_schema()
        row = latest_baseprice_cache(product_uuid)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "cache fetch failed", "message": str(e)},
        )


# -----------------------------
# Routers (non-breaking add-ons)
# -----------------------------
if doorhangers_router is not None:
    app.include_router(doorhangers_router)

if catalog_router is not None:
    app.include_router(catalog_router)

if pricing_tester_router is not None:
    app.include_router(pricing_tester_router)
