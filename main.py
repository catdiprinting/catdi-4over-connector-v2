from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, whoami, product_baseprices, product_optiongroups, auth_debug
from db import ensure_schema, upsert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache


APP_VERSION = {"service": "catdi-4over-connector", "phase": "0.9", "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE"}
app = FastAPI(title="Catdi 4over Connector", version="0.9")


@app.get("/_router_error")
def router_error():
    # You can optionally wire this to real router load diagnostics later.
    return {"ok": True}


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    return {"ok": True}


@app.get("/debug/auth")
def debug_auth():
    # Does NOT reveal secrets
    return auth_debug()


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
                    "error": "4over_request_failed",
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
            content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
        )


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and cache into DB.
    NOTE: This UPSERTS (one row per product_uuid). No duplicates.
    """
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        cache_id = upsert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={"detail": {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "db_error", "message": str(e)})


@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        ensure_schema()
        return {"entities": list_baseprice_cache(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache_list_failed", "message": str(e)})


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
        raise HTTPException(status_code=500, detail={"error": "cache_fetch_failed", "message": str(e)})


def _extract_runsizes_and_colorspecs_from_payload(payload: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    entities = (payload or {}).get("entities", []) or []
    run_map = {}
    col_map = {}
    for r in entities:
        run_uuid = r.get("runsize_uuid")
        run_val = r.get("runsize")
        col_uuid = r.get("colorspec_uuid")
        col_val = r.get("colorspec")
        if run_uuid and run_val:
            run_map[run_uuid] = run_val
        if col_uuid and col_val:
            col_map[col_uuid] = col_val

    runsizes = [{"runsize_uuid": k, "runsize": v} for k, v in sorted(run_map.items(), key=lambda x: int(x[1]))]
    colorspecs = [{"colorspec_uuid": k, "colorspec": v} for k, v in col_map.items()]
    return runsizes, colorspecs


@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    Pull optiongroups from 4over (if auth works) or falls back to cache-derived runsizes/colorspecs if present.
    """
    # First try live optiongroups (this is where you'll later get size/stock/coating/turnaround)
    try:
        og = product_optiongroups(product_uuid)
        return {"ok": True, "product_uuid": product_uuid, "optiongroups": og}
    except FourOverError:
        pass

    # Fallback to cache-derived runsizes/colorspecs so quoting still works if optiongroups is blocked.
    row = latest_baseprice_cache(product_uuid)
    payload = (row or {}).get("payload", {}) or {}
    runsizes, colorspecs = _extract_runsizes_and_colorspecs_from_payload(payload)
    return {"ok": True, "product_uuid": product_uuid, "runsizes": runsizes, "colorspecs": colorspecs, "source": {"used_cache": True}}


def _find_baseprice_row(payload: Dict[str, Any], runsize: Optional[str], colorspec: Optional[str], runsize_uuid: Optional[str], colorspec_uuid: Optional[str]) -> Optional[Dict[str, Any]]:
    entities = (payload or {}).get("entities", []) or []
    for r in entities:
        if runsize_uuid and colorspec_uuid:
            if r.get("runsize_uuid") == runsize_uuid and r.get("colorspec_uuid") == colorspec_uuid:
                return r
        elif runsize and colorspec:
            if str(r.get("runsize")) == str(runsize) and str(r.get("colorspec")) == str(colorspec):
                return r
    return None


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: Optional[str] = Query(None),
    colorspec: Optional[str] = Query(None),
    runsize_uuid: Optional[str] = Query(None),
    colorspec_uuid: Optional[str] = Query(None),
    markup_pct: float = Query(25.0),
    auto_import: bool = Query(False),
):
    """
    Quote from cached baseprices. If cache missing and auto_import=true, fetch + upsert.
    """
    ensure_schema()

    row = latest_baseprice_cache(product_uuid)
    payload = (row or {}).get("payload", {}) or {}

    # optional auto import if cache empty
    if (not payload or not payload.get("entities")) and auto_import:
        bp = product_baseprices(product_uuid)
        upsert_baseprice_cache(product_uuid, bp)
        row = latest_baseprice_cache(product_uuid)
        payload = (row or {}).get("payload", {}) or {}

    if not payload or not payload.get("entities"):
        raise HTTPException(status_code=404, detail="No cached baseprices. Import first or call with auto_import=true.")

    match = _find_baseprice_row(payload, runsize, colorspec, runsize_uuid, colorspec_uuid)
    if not match:
        raise HTTPException(status_code=404, detail="No matching baseprice row for selected options")

    base_price = Decimal(str(match.get("product_baseprice", "0")))

    # sell = base * (1 + markup_pct/100)
    sell_price = (base_price * (Decimal("1") + (Decimal(str(markup_pct)) / Decimal("100")))).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

    qty = int(match.get("runsize") or runsize or 0) if (match.get("runsize") or runsize) else 0
    unit_price = (sell_price / Decimal(qty)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP) if qty else Decimal("0")

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
        "source": {"used_cache": True, "auto_fetch": False},
    }
