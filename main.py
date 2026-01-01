# main.py
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, product_optiongroups, whoami
from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache

APP_VERSION = {"service": "catdi-4over-connector", "phase": "0.9", "build": "ROOT_MAIN_PY_DB_UPSERT_SCHEMA_SAFE"}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


def _four_over_error(e: FourOverError):
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
        return _four_over_error(e)


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        return _four_over_error(e)


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and UPSERT into Postgres (one row per product_uuid).
    """
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return _four_over_error(e)
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
def doorhangers_options(product_uuid: str):
    """
    Returns option groups from 4over so we can wire size/stock/coatings/turnaround next.
    Also returns the currently-supported runsizes/colorspecs derived from cached baseprices (if present).
    """
    try:
        ensure_schema()
        cached = latest_baseprice_cache(product_uuid)
        runsizes = []
        colorspecs = []
        used_cache = False

        if cached and cached.get("payload") and cached["payload"].get("entities"):
            used_cache = True
            seen_r, seen_c = set(), set()
            for row in cached["payload"]["entities"]:
                r_id, r_val = row.get("runsize_uuid"), row.get("runsize")
                c_id, c_val = row.get("colorspec_uuid"), row.get("colorspec")
                if r_id and r_val and r_id not in seen_r:
                    seen_r.add(r_id)
                    runsizes.append({"runsize_uuid": r_id, "runsize": str(r_val)})
                if c_id and c_val and c_id not in seen_c:
                    seen_c.add(c_id)
                    colorspecs.append({"colorspec_uuid": c_id, "colorspec": str(c_val)})

        # Pull optiongroups live (size/stock/coating/turnaround live here)
        optiongroups = product_optiongroups(product_uuid)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsizes": runsizes,
            "colorspecs": colorspecs,
            "optiongroups": optiongroups,  # raw (we’ll normalize next)
            "source": {"used_cache": used_cache},
        }

    except FourOverError as e:
        return _four_over_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options failed", "message": str(e)})


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str,
    markup_pct: float = Query(25.0, ge=0.0, le=300.0),

    # Either provide the UUIDs...
    runsize_uuid: Optional[str] = None,
    colorspec_uuid: Optional[str] = None,

    # ...or provide the display values
    runsize: Optional[str] = None,
    colorspec: Optional[str] = None,

    auto_import: bool = Query(True),
):
    """
    Quote from cached baseprices.
    - If cache missing and auto_import=True: pulls baseprices and upserts.
    """
    try:
        ensure_schema()

        cached = latest_baseprice_cache(product_uuid)
        used_cache = cached is not None

        if not cached and auto_import:
            payload = product_baseprices(product_uuid)
            insert_baseprice_cache(product_uuid, payload)
            cached = latest_baseprice_cache(product_uuid)
            used_cache = True

        if not cached or "payload" not in cached or "entities" not in cached["payload"]:
            raise HTTPException(status_code=404, detail="No baseprice cache found for this product_uuid")

        entities = cached["payload"]["entities"]

        # Find matching row
        match = None
        for row in entities:
            if runsize_uuid and colorspec_uuid:
                if row.get("runsize_uuid") == runsize_uuid and row.get("colorspec_uuid") == colorspec_uuid:
                    match = row
                    break
            elif runsize and colorspec:
                if str(row.get("runsize")) == str(runsize) and str(row.get("colorspec")) == str(colorspec):
                    match = row
                    break

        if not match:
            raise HTTPException(status_code=404, detail="No price match for the provided runsize/colorspec")

        base_price = Decimal(str(match["product_baseprice"]))
        m = Decimal(str(markup_pct)) / Decimal("100")
        sell_price = (base_price * (Decimal("1") + m)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

        qty = int(match["runsize"])
        unit = (sell_price / Decimal(qty)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": match.get("runsize_uuid"),
                "runsize": str(match.get("runsize")),
                "colorspec_uuid": match.get("colorspec_uuid"),
                "colorspec": str(match.get("colorspec")),
            },
            "pricing": {
                "base_price": str(base_price),
                "markup_pct": float(markup_pct),
                "sell_price": str(sell_price),
                "unit_price": str(unit),
                "qty": qty,
            },
            "source": {"used_cache": used_cache, "auto_import": auto_import},
        }

    except FourOverError as e:
        return _four_over_error(e)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "quote failed", "message": str(e)})
