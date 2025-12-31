# main.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, whoami, product_baseprices, product_optiongroups
from db import (
    ensure_schema,
    upsert_baseprice_cache,
    latest_baseprice_cache,
    list_baseprice_cache,
)

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE_SCHEMA_HEALING",
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
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        # Prevent hard crashes
        return JSONResponse(status_code=500, content={"detail": {"error": "server_error", "message": str(e)}})


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
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
                    "canonical": e.canonical,
                }
            },
        )


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and UPSERT into Postgres (no duplicates for the same product_uuid).
    """
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        row = upsert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": row["id"]}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        # Prevent app crash loops -> 502s
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
def doorhangers_options(product_uuid: str = Query(..., min_length=10)):
    """
    Returns parsed optiongroups (sizes, stocks, coatings, turnarounds, etc.)
    directly from 4over (or later: cache these too).
    """
    try:
        data = product_optiongroups(product_uuid)
        # NOTE: we keep this as raw for now; you can normalize later
        return {"ok": True, "product_uuid": product_uuid, "optiongroups": data.get("entities", []), "source": {"used_cache": False}}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: str | None = Query(None),
    colorspec: str | None = Query(None),
    runsize_uuid: str | None = Query(None),
    colorspec_uuid: str | None = Query(None),
    markup_pct: float = Query(25.0, ge=0.0, le=500.0),
    auto_import: bool = Query(True),
):
    """
    Quote using cached baseprices. If missing cache and auto_import=True, imports then quotes.
    """
    try:
        ensure_schema()

        cache_row = latest_baseprice_cache(product_uuid)
        if not cache_row and auto_import:
            payload = product_baseprices(product_uuid)
            cache_row = upsert_baseprice_cache(product_uuid, payload)

        if not cache_row:
            raise HTTPException(status_code=404, detail="No cached baseprices for product_uuid (import first)")

        entities = (cache_row["payload"] or {}).get("entities", [])

        # Find matching baseprice row
        match = None
        for r in entities:
            if runsize_uuid and colorspec_uuid:
                if r.get("runsize_uuid") == runsize_uuid and r.get("colorspec_uuid") == colorspec_uuid:
                    match = r
                    break
            elif runsize and colorspec:
                if str(r.get("runsize")) == str(runsize) and str(r.get("colorspec")) == str(colorspec):
                    match = r
                    break

        if not match:
            raise HTTPException(status_code=404, detail="No matching baseprice for the provided runsize/colorspec inputs")

        base_price_raw = str(match.get("product_baseprice", "0"))
        try:
            base_price = Decimal(base_price_raw)
        except InvalidOperation:
            raise HTTPException(status_code=500, detail=f"Invalid base price from API: {base_price_raw}")

        pct = Decimal(str(markup_pct))
        sell_price = (base_price * (Decimal("1") + (pct / Decimal("100")))).quantize(Decimal("0.0000000001"))

        # qty from runsize
        qty = int(str(match.get("runsize", "0")))
        unit_price = (sell_price / Decimal(qty)).quantize(Decimal("0.0000000001")) if qty else Decimal("0")

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": match.get("runsize_uuid"),
                "runsize": match.get("runsize"),
                "colorspec_uuid": match.get("colorspec_uuid"),
                "colorspec": match.get("colorspec"),
            },
            "pricing": {
                "base_price": str(base_price),
                "markup_pct": float(markup_pct),
                "sell_price": str(sell_price),
                "unit_price": str(unit_price),
                "qty": qty,
            },
            "source": {"used_cache": True, "auto_import": (cache_row is not None and auto_import)},
        }

    except HTTPException:
        raise
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        # Prevent crash loops -> Railway 502
        raise HTTPException(status_code=500, detail={"error": "server_error", "message": str(e)})
