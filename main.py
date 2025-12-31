from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc, delete
from sqlalchemy.exc import SQLAlchemyError
import traceback

import fourover_client as fourover
from fourover_client import FourOverError

from db import SessionLocal, engine
from models import Base, BasePriceCache

SERVICE_NAME = "catdi-4over-connector"
PHASE = "0.9"
BUILD = "ROOT_MAIN_PY_V6_NO_APP_FOLDER_NO_FETCHED_AT"

app = FastAPI(title=SERVICE_NAME, version=PHASE)


# -----------------------------
# Helpers
# -----------------------------
def safe_error(detail: dict, status_code: int = 500):
    """
    Return consistent error payloads (prevents Railway 502 crash loops).
    """
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _latest_cache_row(db, product_uuid: str):
    """
    Get most recent cache row WITHOUT relying on fetched_at.
    We order by id desc (works on your current schema).
    """
    stmt = (
        select(BasePriceCache)
        .where(BasePriceCache.product_uuid == product_uuid)
        .order_by(desc(BasePriceCache.id))
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _extract_entities(payload: dict):
    entities = payload.get("entities", [])
    if not isinstance(entities, list):
        return []
    return entities


def _normalize_colorspec(s: str) -> str:
    return (s or "").strip().replace(" ", "")


def _normalize_runsize(s) -> str:
    return str(s).strip()


def _find_match_from_baseprices(payload: dict, runsize: str, colorspec: str):
    """
    From cached baseprices payload, find a matching entity for runsize + colorspec.
    We expect each entity has runsize + colorspec + their uuids.
    """
    entities = _extract_entities(payload)
    target_runsize = _normalize_runsize(runsize)
    target_colorspec = _normalize_colorspec(colorspec)

    for e in entities:
        e_runsize = _normalize_runsize(e.get("runsize") or e.get("runsize_name") or e.get("qty") or "")
        e_colorspec = _normalize_colorspec(e.get("colorspec") or e.get("colorspec_name") or "")
        if e_runsize == target_runsize and e_colorspec == target_colorspec:
            return e

    return None


def _apply_markup(value: float, markup_pct: float) -> float:
    try:
        pct = float(markup_pct or 0)
    except Exception:
        pct = 0.0
    return round(float(value) * (1.0 + (pct / 100.0)), 2)


# -----------------------------
# Core health/version endpoints
# -----------------------------
@app.get("/version")
def version():
    return {"service": SERVICE_NAME, "phase": PHASE, "build": BUILD}


@app.get("/ping")
def ping():
    return {"ok": True}


# -----------------------------
# DB endpoints
# -----------------------------
@app.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"ok": True}
    except Exception as e:
        return safe_error({"error": "db ping failed", "message": str(e)}, status_code=500)


@app.post("/db/init")
def db_init():
    """
    Creates tables safely.
    If they already exist, don't crash.
    """
    try:
        Base.metadata.create_all(bind=engine)
        # Return table names for sanity
        return {"ok": True, "tables": ["baseprice_cache"]}
    except Exception as e:
        return safe_error({"error": "db init failed", "message": str(e)}, status_code=500)


# -----------------------------
# 4over endpoints
# -----------------------------
@app.get("/4over/whoami")
def whoami():
    try:
        return fourover.whoami()
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over_http_error",
                "status_code": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": getattr(e, "canonical", None),
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected_error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Doorhangers endpoints
# -----------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    try:
        return fourover.product_baseprices(product_uuid)
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over_http_error",
                "status_code": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": getattr(e, "canonical", None),
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected_error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str):
    """
    Fetch baseprices from 4over and REPLACE cache for this product_uuid.
    (No duplicates.)
    """
    try:
        data = fourover.product_baseprices(product_uuid)
        entities = _extract_entities(data)

        if len(entities) == 0:
            return safe_error(
                {"error": "no_baseprices_returned", "product_uuid": product_uuid, "raw": data},
                status_code=400,
            )

        with SessionLocal() as db:
            # delete old cache rows for this product
            db.execute(delete(BasePriceCache).where(BasePriceCache.product_uuid == product_uuid))
            db.commit()

            # insert new cache row
            row = BasePriceCache(product_uuid=product_uuid, payload=data)
            db.add(row)
            db.commit()
            db.refresh(row)

            return {"ok": True, "product_uuid": product_uuid, "cache_id": row.id, "replaced": True}

    except FourOverError as e:
        return safe_error(
            {
                "error": "4over_http_error",
                "status_code": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": getattr(e, "canonical", None),
            },
            status_code=e.status,
        )
    except SQLAlchemyError as e:
        return safe_error({"error": "db_error", "message": str(e)}, status_code=500)
    except Exception as e:
        return safe_error(
            {"error": "unexpected_error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/doorhangers/options")
def doorhanger_options(product_uuid: str = Query(...)):
    """
    Returns option groups from:
    GET /printproducts/products/{product_uuid}/optiongroups

    (Matches what you noted as the correct route.)
    """
    try:
        return fourover.product_optiongroups(product_uuid)
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over_http_error",
                "status_code": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": getattr(e, "canonical", None),
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected_error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/doorhangers/quote")
def doorhanger_quote(
    product_uuid: str = Query(...),
    runsize: str = Query(...),
    colorspec: str = Query(...),
    markup_pct: float = Query(0),
):
    """
    Uses cached baseprices to map runsize/colorspec -> UUIDs,
    then calls 4over productquote endpoint:

    GET /printproducts/productquote?product_uuid=...&colorspec_uuid=...&runsize_uuid=...&turnaroundtime_uuid=...&options[]=...
    (Per API docs.)
    """
    try:
        with SessionLocal() as db:
            row = _latest_cache_row(db, product_uuid)

        # Auto-import if missing cache
        if not row:
            import_result = doorhanger_import(product_uuid)
            if isinstance(import_result, JSONResponse):
                return import_result
            with SessionLocal() as db:
                row = _latest_cache_row(db, product_uuid)

        if not row:
            raise HTTPException(status_code=404, detail={"error": "cache_missing", "product_uuid": product_uuid})

        payload = row.payload if isinstance(row.payload, dict) else {}
        match = _find_match_from_baseprices(payload, runsize=runsize, colorspec=colorspec)

        if not match:
            return safe_error(
                {
                    "error": "no_matching_combination",
                    "product_uuid": product_uuid,
                    "runsize": runsize,
                    "colorspec": colorspec,
                    "hint": "Combination must exist in baseprices entities.",
                },
                status_code=404,
            )

        runsize_uuid = match.get("runsize_uuid")
        colorspec_uuid = match.get("colorspec_uuid")
        turnaround_uuid = (
            match.get("turnaroundtime_uuid")
            or match.get("turnaround_uuid")
        )

        if not (runsize_uuid and colorspec_uuid and turnaround_uuid):
            return safe_error(
                {
                    "error": "missing_required_uuids_in_baseprices_entity",
                    "have": {
                        "runsize_uuid": bool(runsize_uuid),
                        "colorspec_uuid": bool(colorspec_uuid),
                        "turnaround_uuid": bool(turnaround_uuid),
                    },
                    "entity_keys": sorted(list(match.keys())),
                },
                status_code=500,
            )

        # No options chosen yet (we’ll add later).
        quote = fourover.product_quote(
            product_uuid=product_uuid,
            runsize_uuid=runsize_uuid,
            colorspec_uuid=colorspec_uuid,
            turnaround_uuid=turnaround_uuid,
            option_uuids=[],
        )

        # Apply markup to total_price if present
        total = quote.get("total_price")
        try:
            total_val = float(total)
        except Exception:
            total_val = None

        if total_val is not None:
            quote["total_price_with_markup"] = _apply_markup(total_val, markup_pct)
            quote["markup_pct"] = float(markup_pct)

        quote["resolved"] = {
            "runsize": runsize,
            "colorspec": colorspec,
            "runsize_uuid": runsize_uuid,
            "colorspec_uuid": colorspec_uuid,
            "turnaround_uuid": turnaround_uuid,
        }
        return quote

    except FourOverError as e:
        return safe_error(
            {
                "error": "4over_http_error",
                "status_code": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": getattr(e, "canonical", None),
            },
            status_code=e.status,
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        return safe_error(
            {"error": "unexpected_error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Cache debug endpoints (optional but handy)
# -----------------------------
@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        with SessionLocal() as db:
            stmt = select(BasePriceCache).order_by(desc(BasePriceCache.id)).limit(limit)
            rows = db.execute(stmt).scalars().all()

            return {
                "ok": True,
                "count": len(rows),
                "items": [
                    {
                        "id": r.id,
                        "product_uuid": r.product_uuid,
                        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return safe_error(
            {"error": "cache_list_failed", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    try:
        with SessionLocal() as db:
            row = _latest_cache_row(db, product_uuid)

            if not row:
                raise HTTPException(status_code=404, detail={"error": "not_found", "product_uuid": product_uuid})

            return {"ok": True, "id": row.id, "product_uuid": row.product_uuid, "payload": row.payload}

    except HTTPException as he:
        raise he
    except Exception as e:
        return safe_error(
            {"error": "cache_fetch_failed", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )
