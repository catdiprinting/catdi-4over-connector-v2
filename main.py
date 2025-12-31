from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError
import traceback

import fourover_client as fourover
from fourover_client import FourOverError

from db import SessionLocal, engine
from models import Base, BasePriceCache

SERVICE_NAME = "catdi-4over-connector"
PHASE = "0.9"
BUILD = "ROOT_MAIN_PY_V6_ROOT_STABLE"


app = FastAPI(title=SERVICE_NAME, version=PHASE)


# -----------------------------
# Helpers
# -----------------------------
def safe_error(detail: dict, status_code: int = 500):
    """Return consistent error payloads (prevents Railway 502 crash loops)."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


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
        return safe_error(
            {"error": "db ping failed", "message": str(e)},
            status_code=500,
        )


@app.post("/db/init")
def db_init():
    """
    Creates tables safely.
    Also creates the index using IF NOT EXISTS so we never crash on duplicates.
    """
    try:
        # Create table(s)
        Base.metadata.create_all(bind=engine)

        # Create index safely (Postgres + SQLite both support IF NOT EXISTS)
        with engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid ON baseprice_cache (product_uuid)"
            )

        return {"ok": True}
    except Exception as e:
        return safe_error(
            {"error": "db init failed", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


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
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Doorhangers endpoints (baseprices + import)
# -----------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    try:
        return fourover.product_baseprices(product_uuid)
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str):
    """
    Fetch baseprices from 4over and store in DB cache.
    """
    try:
        data = fourover.product_baseprices(product_uuid)
        entities = data.get("entities", [])

        if not isinstance(entities, list) or len(entities) == 0:
            return safe_error(
                {"error": "no baseprices returned", "product_uuid": product_uuid, "raw": data},
                status_code=400,
            )

        with SessionLocal() as db:
            row = BasePriceCache(product_uuid=product_uuid, payload=data)
            db.add(row)
            db.commit()
            db.refresh(row)

            return {"ok": True, "product_uuid": product_uuid, "cache_id": row.id}

    except FourOverError as e:
        return safe_error(
            {
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except SQLAlchemyError as e:
        return safe_error({"error": "db error", "message": str(e)}, status_code=500)
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Cache endpoints
# -----------------------------
@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    """
    Returns the most recent cache rows.
    """
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
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return safe_error(
            {"error": "cache list failed", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    """
    Returns the most recent cached payload for a product_uuid.
    """
    try:
        with SessionLocal() as db:
            stmt = (
                select(BasePriceCache)
                .where(BasePriceCache.product_uuid == product_uuid)
                .order_by(desc(BasePriceCache.id))
                .limit(1)
            )
            row = db.execute(stmt).scalars().first()

            if not row:
                raise HTTPException(
                    status_code=404, detail={"error": "not found", "product_uuid": product_uuid}
                )

            return {"ok": True, "id": row.id, "product_uuid": row.product_uuid, "payload": row.payload}

    except HTTPException as he:
        raise he
    except Exception as e:
        return safe_error(
            {"error": "cache fetch failed", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )
