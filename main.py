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


@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    Returns available dropdown options (runsizes + colorspecs) from cached baseprices payload.
    """
    try:
        ensure_schema()
        row = latest_baseprice_cache(product_uuid)
        if not row:
            raise HTTPException(status_code=404, detail="Not found (no cached payload for product_uuid)")

        payload = row.get("payload") or {}
        entities = payload.get("entities") or []

        runsize_map = {}     # {runsize_uuid: runsize}
        colorspec_map = {}   # {colorspec_uuid: colorspec}

        for e in entities:
            ru = e.get("runsize_uuid")
            rv = e.get("runsize")
            cu = e.get("colorspec_uuid")
            cv = e.get("colorspec")

            if ru and rv:
                runsize_map[ru] = rv
            if cu and cv:
                colorspec_map[cu] = cv

        # Sort by numeric runsize when possible
        def _runsize_sort_key(item):
            _uuid, val = item
            try:
                return (0, int(str(val)))
            except Exception:
                return (1, str(val))

        runsizes = [{"runsize_uuid": k, "runsize": v} for k, v in sorted(runsize_map.items(), key=_runsize_sort_key)]
        colorspecs = [{"colorspec_uuid": k, "colorspec": v} for k, v in sorted(colorspec_map.items(), key=lambda x: x[1])]

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsizes": runsizes,
            "colorspecs": colorspecs,
            "source": {"used_cache": True},
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options failed", "message": str(e)})
