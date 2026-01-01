from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, HTTPException, Query

from fourover_client import FourOverError, client, product_baseprices
from db import ensure_schema, insert_baseprice_cache, latest_baseprice_cache

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


def _to_decimal(x: str | int | float) -> Decimal:
    return Decimal(str(x))


def _money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)).rstrip("0").rstrip(".")


def _ensure_cached(product_uuid: str, auto_import: bool) -> dict:
    ensure_schema()
    row = latest_baseprice_cache(product_uuid)
    if row:
        return row

    if not auto_import:
        raise HTTPException(status_code=404, detail="No cache for product_uuid. Run /doorhangers/import/{product_uuid}")

    payload = product_baseprices(product_uuid)
    insert_baseprice_cache(product_uuid, payload)
    row = latest_baseprice_cache(product_uuid)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create cache row")
    return row


@router.get("/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        raise HTTPException(status_code=401 if e.status == 401 else 502, detail={
            "error": "4over_request_failed",
            "status": e.status,
            "url": e.url,
            "body": e.body,
            "canonical": e.canonical,
        })


@router.post("/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and UPSERT into DB (1 row per product_uuid).
    """
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        raise HTTPException(status_code=401 if e.status == 401 else 502, detail={
            "error": "4over_request_failed",
            "status": e.status,
            "url": e.url,
            "body": e.body,
            "canonical": e.canonical,
        })


@router.get("/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    For now: options derived from baseprices (runsize + colorspec).
    Next phase: enrich with /optiongroups (size, stock, coating, turnaround).
    """
    row = _ensure_cached(product_uuid, auto_import=True)
    entities = (row.get("payload") or {}).get("entities", [])

    runsizes = {}
    colorspecs = {}

    for it in entities:
        ru = it.get("runsize_uuid")
        rv = it.get("runsize")
        cu = it.get("colorspec_uuid")
        cv = it.get("colorspec")
        if ru and rv:
            runsizes[ru] = rv
        if cu and cv:
            colorspecs[cu] = cv

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in sorted(runsizes.items(), key=lambda x: int(x[1]))],
        "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspecs.items()],
        "source": {"used_cache": True},
    }


@router.get("/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: str | None = Query(None),
    colorspec: str | None = Query(None),
    runsize_uuid: str | None = Query(None),
    colorspec_uuid: str | None = Query(None),
    markup_pct: float = Query(25.0, ge=0.0, le=500.0),
    auto_import: bool = Query(False),
):
    """
    Quote using latest cached baseprices.
    Accepts either (runsize + colorspec) OR (runsize_uuid + colorspec_uuid).
    """
    row = _ensure_cached(product_uuid, auto_import=auto_import)
    entities = (row.get("payload") or {}).get("entities", [])

    # Find matching baseprice row
    match = None
    for it in entities:
        if runsize_uuid and colorspec_uuid:
            if it.get("runsize_uuid") == runsize_uuid and it.get("colorspec_uuid") == colorspec_uuid:
                match = it
                break
        else:
            if runsize and colorspec and it.get("runsize") == str(runsize) and it.get("colorspec") == str(colorspec):
                match = it
                break

    if not match:
        raise HTTPException(status_code=404, detail="No matching baseprice row for selected options")

    base = _to_decimal(match["product_baseprice"])
    pct = _to_decimal(markup_pct) / Decimal("100")
    sell = (base * (Decimal("1") + pct))

    qty = int(match["runsize"])
    unit = sell / Decimal(qty)

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
            "base_price": _money(base),
            "markup_pct": float(markup_pct),
            "sell_price": _money(sell),
            "unit_price": _money(unit),
            "qty": qty,
        },
        "source": {"used_cache": True, "auto_fetch": auto_import},
    }
