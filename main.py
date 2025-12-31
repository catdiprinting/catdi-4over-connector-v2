# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami
from db import (
    ensure_schema,
    insert_baseprice_cache,
    list_baseprice_cache,
    latest_baseprice_cache,
    # If your code already has helpers used by /doorhangers/options and /doorhangers/quote,
    # keep them in db.py or a doorhangers.py module.
    get_cached_baseprices_for_product,
    find_baseprice_match,
    compute_sell_price,
)

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


# ----------------------------
# Health / Version
# ----------------------------
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


# ----------------------------
# 4over auth sanity check
# ----------------------------
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


# ----------------------------
# Doorhangers: Baseprices (raw)
# ----------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    """
    Fetch baseprices directly from 4over (no DB required).
    """
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


# ----------------------------
# Cache endpoints
# ----------------------------
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


# ----------------------------
# Doorhangers: Options (runsize/colorspec)
# ----------------------------
@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str):
    """
    Returns distinct runsizes + colorspecs for the product from cached baseprices.
    """
    try:
        ensure_schema()
        rows, used_cache = get_cached_baseprices_for_product(product_uuid, auto_fetch=False)

        runsizes = {}
        colorspecs = {}

        for r in rows:
            runsizes[r["runsize_uuid"]] = r["runsize"]
            colorspecs[r["colorspec_uuid"]] = r["colorspec"]

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in runsizes.items()],
            "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspecs.items()],
            "source": {"used_cache": used_cache},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options failed", "message": str(e)})


# ----------------------------
# Doorhangers: Quote
# ----------------------------
@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str,
    markup_pct: float = Query(25.0, ge=0.0, le=500.0),

    # allow either (runsize + colorspec) OR uuids
    runsize: str | None = None,
    colorspec: str | None = None,
    runsize_uuid: str | None = None,
    colorspec_uuid: str | None = None,
):
    """
    Quote uses cached baseprices only (auto_fetch defaults to False based on your latest curl output).
    """
    try:
        ensure_schema()

        rows, used_cache = get_cached_baseprices_for_product(product_uuid, auto_fetch=False)

        match = find_baseprice_match(
            rows=rows,
            runsize=runsize,
            colorspec=colorspec,
            runsize_uuid=runsize_uuid,
            colorspec_uuid=colorspec_uuid,
        )
        if not match:
            raise HTTPException(status_code=404, detail="No matching base price found")

        pricing = compute_sell_price(
            base_price_str=match["product_baseprice"],
            qty=int(match["runsize"]),
            markup_pct=float(markup_pct),
        )

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": match["runsize_uuid"],
                "runsize": match["runsize"],
                "colorspec_uuid": match["colorspec_uuid"],
                "colorspec": match["colorspec"],
            },
            "pricing": pricing,
            "source": {"used_cache": used_cache, "auto_fetch": False},
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "quote failed", "message": str(e)})


# ----------------------------
# NEXT: Extended options / config
# ----------------------------
# Add these next without touching existing endpoints:
#
# 1) GET /doorhangers/product/{product_uuid}/config
# 2) POST /doorhangers/import-config/{product_uuid}
# 3) GET /doorhangers/options-extended?product_uuid=...
#
# Those will pull/return option groups like size/stock/coating/turnaround.
