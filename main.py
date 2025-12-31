from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami
from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache


APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE_V2",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


# ----------------------------
# Helpers
# ----------------------------
def _norm(s: Any) -> str:
    return str(s or "").strip()


def _norm_colorspec(s: Any) -> str:
    # normalize "4/4", "4 / 4" -> "4/4"
    return _norm(s).replace(" ", "")


def _to_decimal(v: Any) -> Decimal:
    # v might be numeric or string like "92.8679..."
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail={"error": "invalid_decimal", "value": v})


def _round_money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _extract_entities(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ents = payload.get("entities", [])
    return ents if isinstance(ents, list) else []


def _unique_options_from_entities(entities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    run_map: Dict[str, str] = {}
    col_map: Dict[str, str] = {}

    for e in entities:
        run_label = _norm(e.get("runsize"))
        run_uuid = _norm(e.get("runsize_uuid"))
        if run_label and run_uuid:
            run_map.setdefault(run_label, run_uuid)

        col_label = _norm_colorspec(e.get("colorspec"))
        col_uuid = _norm(e.get("colorspec_uuid"))
        if col_label and col_uuid:
            col_map.setdefault(col_label, col_uuid)

    runsizes = [{"runsize": k, "runsize_uuid": v} for k, v in sorted(run_map.items(), key=lambda x: int(x[0]))]
    colorspecs = [{"colorspec": k, "colorspec_uuid": v} for k, v in sorted(col_map.items(), key=lambda x: x[0])]

    return {"runsizes": runsizes, "colorspecs": colorspecs}


def _find_match_in_entities(
    entities: List[Dict[str, Any]],
    runsize: Optional[str],
    colorspec: Optional[str],
    runsize_uuid: Optional[str],
    colorspec_uuid: Optional[str],
) -> Optional[Dict[str, Any]]:
    # Prefer UUID match if provided
    if runsize_uuid and colorspec_uuid:
        ru = _norm(runsize_uuid)
        cu = _norm(colorspec_uuid)
        for e in entities:
            if _norm(e.get("runsize_uuid")) == ru and _norm(e.get("colorspec_uuid")) == cu:
                return e

    # Otherwise match by labels
    if runsize and colorspec:
        rl = _norm(runsize)
        cl = _norm_colorspec(colorspec)
        for e in entities:
            if _norm(e.get("runsize")) == rl and _norm_colorspec(e.get("colorspec")) == cl:
                return e

    return None


# ----------------------------
# Core endpoints
# ----------------------------
@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    # Keep it simple; if app is up, db/ping returns ok.
    return {"ok": True}


@app.post("/db/init")
def db_init():
    try:
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


# ----------------------------
# 4over sanity
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
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "unexpected error", "message": str(e)})


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


# ----------------------------
# Cache import/list/get
# ----------------------------
@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and cache into Postgres.
    """
    try:
        ensure_schema()
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


# ----------------------------
# Calculator endpoints
# ----------------------------
@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    Returns available runsizes and colorspecs derived from the latest cached baseprices payload.
    """
    try:
        ensure_schema()
        row = latest_baseprice_cache(product_uuid)
        if not row:
            raise HTTPException(status_code=404, detail={"error": "no cache for product", "product_uuid": product_uuid})

        payload = row.get("payload") if isinstance(row, dict) else row.payload  # be defensive
        entities = _extract_entities(payload or {})
        opts = _unique_options_from_entities(entities)

        return {"ok": True, "product_uuid": product_uuid, "source": {"used_cache": True}, **opts}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options failed", "message": str(e)})


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: Optional[str] = Query(None),
    colorspec: Optional[str] = Query(None),
    runsize_uuid: Optional[str] = Query(None),
    colorspec_uuid: Optional[str] = Query(None),
    markup_pct: float = Query(0, ge=0, le=300),
    auto_fetch: bool = Query(False),
):
    """
    Quotes from cached baseprices (stable) with optional auto_fetch to populate cache.
    - You may pass runsize/colorspec labels OR UUIDs.
    """
    try:
        ensure_schema()

        row = latest_baseprice_cache(product_uuid)

        if not row and auto_fetch:
            payload = product_baseprices(product_uuid)
            insert_baseprice_cache(product_uuid, payload)
            row = latest_baseprice_cache(product_uuid)

        if not row:
            raise HTTPException(
                status_code=404,
                detail={"error": "no cache for product (run import first)", "product_uuid": product_uuid},
            )

        payload = row.get("payload") if isinstance(row, dict) else row.payload
        entities = _extract_entities(payload or {})
        if not entities:
            raise HTTPException(status_code=500, detail={"error": "cache payload had no entities", "product_uuid": product_uuid})

        match = _find_match_in_entities(
            entities,
            runsize=runsize,
            colorspec=colorspec,
            runsize_uuid=runsize_uuid,
            colorspec_uuid=colorspec_uuid,
        )

        if not match:
            # return helpful options so you can see valid combos
            opts = _unique_options_from_entities(entities)
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no matching pricing row in cache",
                    "requested": {
                        "runsize": runsize,
                        "colorspec": colorspec,
                        "runsize_uuid": runsize_uuid,
                        "colorspec_uuid": colorspec_uuid,
                    },
                    "available": opts,
                },
            )

        base_price = _to_decimal(match.get("product_baseprice"))
        pct = Decimal(str(markup_pct)) / Decimal("100")
        sell = _round_money(base_price * (Decimal("1") + pct))

        qty = _to_decimal(match.get("runsize") or runsize or "0")
        unit = Decimal("0.00")
        if qty > 0:
            unit = _round_money(sell / qty)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": _norm(match.get("runsize_uuid")),
                "runsize": _norm(match.get("runsize")),
                "colorspec_uuid": _norm(match.get("colorspec_uuid")),
                "colorspec": _norm_colorspec(match.get("colorspec")),
            },
            "pricing": {
                "base_price": str(base_price),
                "markup_pct": float(markup_pct),
                "sell_price": str(sell),
                "unit_price": str(unit),
                "qty": int(qty) if qty > 0 else 0,
            },
            "source": {"used_cache": True, "auto_fetch": auto_fetch},
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
