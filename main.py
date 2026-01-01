from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, whoami, product_baseprices
from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache

from doorhangers import router as doorhangers_router

APP_VERSION = {"service": "catdi-4over-connector", "phase": "0.9", "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE"}

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
    try:
        return ensure_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


@app.get("/4over/whoami")
def four_over_whoami():
    try:
        return whoami()
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={"detail": {"error": "4over request failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
        )


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={"detail": {"error": "4over request failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
        )


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and cache into DB (UPSERT: 1 row per product_uuid).
    """
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={"detail": {"error": "4over request failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "db error", "message": str(e)})


@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        ensure_schema()
        return {"entities": list_baseprice_cache(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache list failed", "message": str(e)})


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
        raise HTTPException(status_code=500, detail={"error": "cache fetch failed", "message": str(e)})


@app.get("/_router_error")
def router_error_probe():
    """
    Helpful when Railway shows 502s. If your app boots, this returns ok:true.
    If imports fail, you’ll see the exception message in Railway logs (and usually never reach this).
    """
    return {"ok": True}
