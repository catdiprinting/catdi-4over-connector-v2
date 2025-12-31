# main.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami
from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache

APP_VERSION = {"service": "catdi-4over-connector", "phase": "0.9", "build": "ROOT_MAIN_PY_AUTH_LOCKED_DB_SAFE_PLUS_QUOTE_V1"}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


# ----------------------------
# Helpers (safe, no side effects)
# ----------------------------
def _to_decimal(value: Any) -> Decimal:
    """
    Convert strings/numbers like "92.8679..." to Decimal safely.
    """
    if value is None:
        raise ValueError("value is None")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid decimal value: {value}") from e


def _find_baseprice_row(
    payload: dict,
    *,
    runsize_uuid: Optional[str] = None,
    colorspec_uuid: Optional[str] = None,
    runsize: Optional[str] = None,
    colorspec: Optional[str] = None,
) -> Optional[dict]:
    """
    Finds a matching baseprice row in 4over payload:
    payload["entities"] = [{runsize_uuid, colorspec_uuid, runsize, colorspec, product_baseprice, ...}, ...]
    """
    entities = (payload or {}).get("entities") or []
    if not isinstance(entities, list):
        return None

    def match(row: dict) -> bool:
        if not isinstance(row, dict):
            return False

        # Prefer UUID matching when provided (most reliable)
        if runsize_uuid and row.get("runsize_uuid") != runsize_uuid:
            return False
        if colorspec_uuid and row.get("colorspec_uuid") != colorspec_uuid:
            return False

        # If UUIDs not provided, allow label matching
        if not runsize_uuid and runsize is not None and str(row.get("runsize")) != str(runsize):
            return False
        if not colorspec_uuid and colorspec is not None and str(row.get("colorspec")) != str(colorspec):
            return False

        # Must have price
        return row.get("product_baseprice") is not None

    for row in entities:
        if match(row):
            return row
    return None


def _get_cached_payload(product_uuid: str) -> Optional[dict]:
    """
    Returns cached payload dict or None.
    latest_baseprice_cache(product_uuid) returns something like:
      {"id":..., "product_uuid":..., "payload": {...}, "created_at": ...}
    """
    row = latest_baseprice_cache(product_uuid)
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


# ----------------------------
# Existing endpoints (UNCHANGED behavior)
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


# ----------------------------
# NEW: Doorhanger quote endpoint (SAFE add-on)
# ----------------------------
@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(..., description="4over product UUID"),
    # Prefer UUIDs for matching
    runsize_uuid: Optional[str] = Query(None, description="runsize_uuid from 4over baseprices row"),
    colorspec_uuid: Optional[str] = Query(None, description="colorspec_uuid from 4over baseprices row"),
    # Optional label matching (fallback)
    runsize: Optional[str] = Query(None, description='runsize label e.g. "250"'),
    colorspec: Optional[str] = Query(None, description='colorspec label e.g. "4/4"'),
    qty: Optional[int] = Query(None, ge=1, description="Optional convenience: the runsize quantity (for unit price). If omitted, we try to parse from runsize."),
    markup_pct: float = Query(0.0, ge=0.0, le=500.0, description="Markup percent (e.g. 20 = 20%)"),
    auto_fetch: bool = Query(True, description="If not cached, fetch from 4over live (GET)"),
):
    """
    Returns a single price point from cached baseprices (or live 4over if auto_fetch=true).

    Example (UUID-driven):
      /doorhangers/quote?product_uuid=...&runsize_uuid=...&colorspec_uuid=...&markup_pct=25

    Example (label-driven fallback):
      /doorhangers/quote?product_uuid=...&runsize=250&colorspec=4/4&markup_pct=25
    """
    try:
        ensure_schema()

        # 1) Load payload (cache first)
        payload = _get_cached_payload(product_uuid)

        # 2) If not cached, optionally fetch from 4over
        if payload is None:
            if not auto_fetch:
                raise HTTPException(status_code=404, detail="No cached baseprices for this product. Run /doorhangers/import/{product_uuid} or set auto_fetch=true.")
            try:
                payload = product_baseprices(product_uuid)
            except FourOverError as e:
                return JSONResponse(
                    status_code=401 if e.status == 401 else 502,
                    content={"detail": {"error": "4over request failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical}},
                )

        # 3) Find matching row
        row = _find_baseprice_row(
            payload,
            runsize_uuid=runsize_uuid,
            colorspec_uuid=colorspec_uuid,
            runsize=runsize,
            colorspec=colorspec,
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Price point not found",
                    "hint": "Provide runsize_uuid + colorspec_uuid (preferred) or runsize + colorspec.",
                },
            )

        # 4) Compute numbers
        base_price = _to_decimal(row.get("product_baseprice"))
        markup_multiplier = Decimal("1") + (Decimal(str(markup_pct)) / Decimal("100"))
        sell_price = (base_price * markup_multiplier)

        # Unit price (optional)
        inferred_qty: Optional[int] = None
        if qty is not None:
            inferred_qty = int(qty)
        else:
            # Try to parse from row["runsize"] if it's an int-like string
            rs = row.get("runsize")
            try:
                inferred_qty = int(str(rs))
            except Exception:
                inferred_qty = None

        unit_price = None
        if inferred_qty and inferred_qty > 0:
            unit_price = (sell_price / Decimal(inferred_qty))

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "match": {
                "runsize_uuid": row.get("runsize_uuid"),
                "runsize": row.get("runsize"),
                "colorspec_uuid": row.get("colorspec_uuid"),
                "colorspec": row.get("colorspec"),
            },
            "pricing": {
                "base_price": str(base_price),
                "markup_pct": markup_pct,
                "sell_price": str(sell_price),
                "unit_price": (str(unit_price) if unit_price is not None else None),
                "qty": inferred_qty,
            },
            "source": {
                "used_cache": _get_cached_payload(product_uuid) is not None,
                "auto_fetch": auto_fetch,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "quote failed", "message": str(e)})
