# main.py
import os
import hashlib
import traceback

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

APP_VERSION = {"service": "catdi-4over-connector", "phase": "0.9", "build": "BOOT_SAFE_DB_UPSERT_AUTH_STABLE"}

app = FastAPI(title="Catdi 4over Connector", version="0.9")

# capture boot/import errors safely
BOOT_ERROR = None

def _set_boot_error(e: Exception):
    global BOOT_ERROR
    BOOT_ERROR = {
        "ok": False,
        "error": str(e),
        "trace": traceback.format_exc().splitlines()[-20:],  # last 20 lines
    }

@app.get("/_router_error")
def router_error():
    return BOOT_ERROR or {"ok": True}

@app.get("/version")
def version():
    return APP_VERSION

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/db/ping")
def db_ping():
    return {"ok": True}

# Import db + 4over lazily so app can boot even if they break
try:
    from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache
except Exception as e:
    _set_boot_error(e)
    ensure_schema = None
    insert_baseprice_cache = None
    list_baseprice_cache = None
    latest_baseprice_cache = None

try:
    from fourover_client import FourOverError, whoami, product_baseprices, product_optiongroups
except Exception as e:
    _set_boot_error(e)
    FourOverError = None
    whoami = None
    product_baseprices = None
    product_optiongroups = None

@app.get("/debug/auth")
def debug_auth():
    # never crash; never leak secrets
    apikey = os.getenv("FOUR_OVER_APIKEY", "")
    pkey = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
    base_url = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")

    def fp(s: str) -> str:
        if not s:
            return ""
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

    return {
        "ok": True,
        "base_url": (base_url or "").strip(),
        "apikey_present": bool(apikey.strip()),
        "apikey_len": len(apikey.strip()),
        "apikey_preview": (apikey.strip()[:4] + "…" + apikey.strip()[-2:]) if apikey.strip() else "",
        "private_key_present": bool(pkey.strip()),
        "private_key_len": len(pkey.strip()),
        "private_key_sha256_12": fp(pkey.strip()),
        "boot_error_present": bool(BOOT_ERROR),
    }

@app.post("/db/init")
def db_init():
    if ensure_schema is None:
        raise HTTPException(status_code=500, detail={"error": "db module failed to import", "boot_error": BOOT_ERROR})
    try:
        return ensure_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})

@app.get("/4over/whoami")
def four_over_whoami():
    if whoami is None:
        return JSONResponse(status_code=500, content={"detail": {"error": "fourover_client failed to import", "boot_error": BOOT_ERROR}})
    try:
        return whoami()
    except Exception as e:
        # include 4over error info if available
        if FourOverError and isinstance(e, FourOverError):
            return JSONResponse(
                status_code=401 if e.status == 401 else 502,
                content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
            )
        return JSONResponse(status_code=502, content={"detail": {"error": "whoami_failed", "message": str(e)}})

@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    if product_baseprices is None:
        return JSONResponse(status_code=500, content={"detail": {"error": "fourover_client failed to import", "boot_error": BOOT_ERROR}})
    try:
        return product_baseprices(product_uuid)
    except Exception as e:
        if FourOverError and isinstance(e, FourOverError):
            return JSONResponse(
                status_code=401 if e.status == 401 else 502,
                content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
            )
        return JSONResponse(status_code=502, content={"detail": {"error": "baseprices_failed", "message": str(e)}})

@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    if ensure_schema is None or insert_baseprice_cache is None:
        raise HTTPException(status_code=500, detail={"error": "db module failed to import", "boot_error": BOOT_ERROR})
    if product_baseprices is None:
        raise HTTPException(status_code=500, detail={"error": "fourover_client failed to import", "boot_error": BOOT_ERROR})

    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)

        # STOP poisoning cache with {}
        if not isinstance(payload, dict) or "entities" not in payload or not isinstance(payload["entities"], list) or len(payload["entities"]) == 0:
            raise HTTPException(status_code=502, detail={"error": "bad_payload_from_4over", "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None})

        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except HTTPException:
        raise
    except Exception as e:
        if FourOverError and isinstance(e, FourOverError):
            return JSONResponse(
                status_code=401 if e.status == 401 else 502,
                content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
            )
        raise HTTPException(status_code=500, detail={"error": "import_failed", "message": str(e)})

@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    if ensure_schema is None or list_baseprice_cache is None:
        raise HTTPException(status_code=500, detail={"error": "db module failed to import", "boot_error": BOOT_ERROR})
    try:
        ensure_schema()
        return {"entities": list_baseprice_cache(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache_list_failed", "message": str(e)})

@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    if ensure_schema is None or latest_baseprice_cache is None:
        raise HTTPException(status_code=500, detail={"error": "db module failed to import", "boot_error": BOOT_ERROR})
    try:
        ensure_schema()
        row = latest_baseprice_cache(product_uuid)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache_fetch_failed", "message": str(e)})

@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str):
    """
    Pulls optiongroups from 4over (if auth works) or falls back to cache-derived runsizes/colorspecs if present.
    """
    # First try: derive from cached baseprices
    try:
        if latest_baseprice_cache:
            row = latest_baseprice_cache(product_uuid)
        else:
            row = None
        payload = (row or {}).get("payload") or {}
        entities = payload.get("entities") if isinstance(payload, dict) else None
        if isinstance(entities, list) and entities:
            runs = {}
            cols = {}
            for r in entities:
                if r.get("runsize_uuid") and r.get("runsize"):
                    runs[r["runsize_uuid"]] = r["runsize"]
                if r.get("colorspec_uuid") and r.get("colorspec"):
                    cols[r["colorspec_uuid"]] = r["colorspec"]
            return {
                "ok": True,
                "product_uuid": product_uuid,
                "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in runs.items()],
                "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in cols.items()],
                "source": {"used_cache": True},
            }
    except Exception:
        pass

    # Second try: live optiongroups call
    if product_optiongroups is None:
        return {"ok": True, "product_uuid": product_uuid, "runsizes": [], "colorspecs": [], "source": {"used_cache": False, "live": False}}

    try:
        og = product_optiongroups(product_uuid)
        return {"ok": True, "product_uuid": product_uuid, "optiongroups": og, "source": {"used_cache": False, "live": True}}
    except Exception as e:
        if FourOverError and isinstance(e, FourOverError):
            return JSONResponse(
                status_code=401 if e.status == 401 else 502,
                content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
            )
        return JSONResponse(status_code=502, content={"detail": {"error": "options_failed", "message": str(e)}})

@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str,
    runsize: str | None = None,
    colorspec: str | None = None,
    runsize_uuid: str | None = None,
    colorspec_uuid: str | None = None,
    markup_pct: float = 25.0,
    auto_import: bool = False,
):
    if latest_baseprice_cache is None:
        raise HTTPException(status_code=500, detail={"error": "db module failed to import", "boot_error": BOOT_ERROR})

    row = latest_baseprice_cache(product_uuid)
    payload = (row or {}).get("payload") or {}
    entities = payload.get("entities") if isinstance(payload, dict) else []

    # optional auto-import if cache missing AND allowed
    if (not entities) and auto_import:
        # call import endpoint logic directly
        if product_baseprices and insert_baseprice_cache and ensure_schema:
            ensure_schema()
            payload2 = product_baseprices(product_uuid)
            if isinstance(payload2, dict) and isinstance(payload2.get("entities"), list) and payload2["entities"]:
                insert_baseprice_cache(product_uuid, payload2)
                row = latest_baseprice_cache(product_uuid)
                payload = (row or {}).get("payload") or {}
                entities = payload.get("entities") if isinstance(payload, dict) else []

    if not entities:
        raise HTTPException(status_code=404, detail="No cached pricing for product (import first or auto_import=true).")

    match = None
    for r in entities:
        ok_run = (runsize_uuid and r.get("runsize_uuid") == runsize_uuid) or (runsize and r.get("runsize") == str(runsize))
        ok_col = (colorspec_uuid and r.get("colorspec_uuid") == colorspec_uuid) or (colorspec and r.get("colorspec") == str(colorspec))
        if ok_run and ok_col:
            match = r
            break

    if not match:
        raise HTTPException(status_code=404, detail="No matching baseprice row for selected options")

    from decimal import Decimal, ROUND_HALF_UP

    base_price = Decimal(str(match["product_baseprice"]))
    pct = Decimal(str(markup_pct)) / Decimal("100")
    sell = (base_price * (Decimal("1") + pct)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

    qty = int(match.get("runsize") or runsize or 1)
    unit = (sell / Decimal(qty)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

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
            "sell_price": str(sell),
            "unit_price": str(unit),
            "qty": qty,
        },
        "source": {"used_cache": True, "auto_fetch": bool(auto_import)},
    }
