# main.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

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


# -------------------------
# Helpers
# -------------------------

def _decimal(s: Any) -> Decimal:
    try:
        return Decimal(str(s))
    except Exception:
        return Decimal("0")


def _money(x: Decimal) -> str:
    # keep high precision strings similar to 4over numeric output
    return format(x, "f")


def _unit_price(total: Decimal, qty: int) -> Decimal:
    if qty <= 0:
        return Decimal("0")
    return (total / Decimal(qty)).quantize(Decimal("0.0000000000000001"), rounding=ROUND_HALF_UP)


def _extract_baseprice_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    4over baseprices returns: {"entities":[{...}], "totalResults":..., ...}
    We only care about entities.
    """
    if not payload:
        return []
    entities = payload.get("entities", [])
    if isinstance(entities, list):
        return entities
    return []


def _load_cached_payload(product_uuid: str) -> Optional[Dict[str, Any]]:
    """
    latest_baseprice_cache(product_uuid) returns either:
      - None
      - a dict like {"id":..., "product_uuid":..., "payload":{...}, "created_at":...}
    """
    row = latest_baseprice_cache(product_uuid)
    if not row:
        return None
    payload = row.get("payload")
    if isinstance(payload, dict):
        return payload
    return None


def _ensure_cached_baseprices(product_uuid: str, auto_fetch: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Returns (payload, source_meta)
    source_meta example: {"used_cache": True/False, "auto_fetch": True/False}
    """
    ensure_schema()

    cached = _load_cached_payload(product_uuid)
    if cached and _extract_baseprice_rows(cached):
        return cached, {"used_cache": True, "auto_fetch": False}

    if not auto_fetch:
        # cache miss and not allowed to fetch
        raise HTTPException(status_code=404, detail="Not found in cache")

    # Fetch from 4over, then cache
    payload = product_baseprices(product_uuid)
    insert_baseprice_cache(product_uuid, payload)
    return payload, {"used_cache": False, "auto_fetch": True}


def _unique_runsizes_and_colorspecs(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    runsize_map: Dict[str, str] = {}
    colorspec_map: Dict[str, str] = {}

    for r in rows:
        ruuid = str(r.get("runsize_uuid", "")).strip()
        rval = str(r.get("runsize", "")).strip()
        cuuid = str(r.get("colorspec_uuid", "")).strip()
        cval = str(r.get("colorspec", "")).strip()

        if ruuid and rval:
            runsize_map[ruuid] = rval
        if cuuid and cval:
            colorspec_map[cuuid] = cval

    runsizes = [{"runsize_uuid": k, "runsize": v} for k, v in runsize_map.items()]
    colorspecs = [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspec_map.items()]

    # sort numerically by runsize if possible, else alpha
    def _runsize_key(x: Dict[str, str]):
        try:
            return int(x["runsize"])
        except Exception:
            return 10**18

    runsizes.sort(key=_runsize_key)
    colorspecs.sort(key=lambda x: x["colorspec"])

    return runsizes, colorspecs


def _find_match(
    rows: List[Dict[str, Any]],
    runsize: Optional[str],
    runsize_uuid: Optional[str],
    colorspec: Optional[str],
    colorspec_uuid: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Match priority:
      1) runsize_uuid + colorspec_uuid
      2) runsize + colorspec (string match)
    """
    ruuid = (runsize_uuid or "").strip()
    cuuid = (colorspec_uuid or "").strip()
    rtxt = (runsize or "").strip()
    ctxt = (colorspec or "").strip()

    if ruuid and cuuid:
        for r in rows:
            if str(r.get("runsize_uuid", "")).strip() == ruuid and str(r.get("colorspec_uuid", "")).strip() == cuuid:
                return r

    if rtxt and ctxt:
        for r in rows:
            if str(r.get("runsize", "")).strip() == rtxt and str(r.get("colorspec", "")).strip() == ctxt:
                return r

    return None


# -------------------------
# Core service endpoints
# -------------------------

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


# -------------------------
# 4over passthrough endpoints
# -------------------------

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


# -------------------------
# Cache read endpoints
# -------------------------

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


# -------------------------
# Doorhanger "calculator" endpoints
# -------------------------

@app.get("/doorhangers/options")
def doorhangers_options(
    product_uuid: str = Query(...),
    auto_fetch: bool = Query(True),
):
    """
    Returns available runsizes and colorspecs from cached baseprices.
    If cache missing and auto_fetch=True, will fetch from 4over then cache.
    """
    try:
        payload, source = _ensure_cached_baseprices(product_uuid, auto_fetch=auto_fetch)
        rows = _extract_baseprice_rows(payload)
        runsizes, colorspecs = _unique_runsizes_and_colorspecs(rows)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsizes": runsizes,
            "colorspecs": colorspecs,
            "source": {"used_cache": source["used_cache"]},
        }
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options failed", "message": str(e)})


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    # match by either value...
    runsize: Optional[str] = Query(None),
    colorspec: Optional[str] = Query(None),
    # ...or match by uuid
    runsize_uuid: Optional[str] = Query(None),
    colorspec_uuid: Optional[str] = Query(None),
    markup_pct: float = Query(0.0, ge=0.0, le=500.0),
    auto_fetch: bool = Query(True),
):
    """
    Quote:
      - Looks in cached baseprices for runsize/colorspec match
      - If no cache and auto_fetch=True, pulls from 4over and caches
      - Applies markup_pct to base price and returns total + unit price
    """
    try:
        payload, source = _ensure_cached_baseprices(product_uuid, auto_fetch=auto_fetch)
        rows = _extract_baseprice_rows(payload)

        match = _find_match(rows, runsize, runsize_uuid, colorspec, colorspec_uuid)
        if not match:
            # Provide friendly error with available options
            runsizes, colorspecs = _unique_runsizes_and_colorspecs(rows)
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no price match",
                    "hint": "Use /doorhangers/options then pass runsize+colorspec OR runsize_uuid+colorspec_uuid",
                    "runsizes": runsizes,
                    "colorspecs": colorspecs,
                },
            )

        base_price = _decimal(match.get("product_baseprice"))
        qty = 0
        try:
            qty = int(str(match.get("runsize", "")).strip() or "0")
        except Exception:
            qty = 0

        m = Decimal(str(markup_pct)) / Decimal("100")
        sell = (base_price * (Decimal("1") + m)).quantize(Decimal("0.0000000000000001"), rounding=ROUND_HALF_UP)
        unit = _unit_price(sell, qty)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": str(match.get("runsize_uuid", "")),
                "runsize": str(match.get("runsize", "")),
                "colorspec_uuid": str(match.get("colorspec_uuid", "")),
                "colorspec": str(match.get("colorspec", "")),
            },
            "pricing": {
                "base_price": _money(base_price),
                "markup_pct": float(markup_pct),
                "sell_price": _money(sell),
                "unit_price": _money(unit),
                "qty": qty,
            },
            "source": {
                "used_cache": bool(source["used_cache"]),
                "auto_fetch": bool(source["auto_fetch"]),
            },
        }

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "quote failed", "message": str(e)})
