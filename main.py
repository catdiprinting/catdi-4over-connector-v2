import os
import time
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from db import engine, SessionLocal
from fourover_client import fourover_get  # uses your signing + requests logic


SERVICE_NAME = "catdi-4over-connector"
PHASE = "0.9"
BUILD = os.getenv("BUILD", "ROOT_MAIN_PY_V7_NO_MODELS_SCHEMA_SAFE")


app = FastAPI(title=SERVICE_NAME)


# -------------------------
# DB helpers
# -------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> Dict[str, Any]:
    """
    Create or migrate the baseprice_cache table.

    Key rule: DO NOT assume the table is clean.
    If table exists but is missing columns (like payload), we add them.
    """
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
            # 1) Create table if missing
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id BIGSERIAL PRIMARY KEY,
                    product_uuid VARCHAR NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))

            # 2) Add payload column if missing (this fixes your current failure)
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name='baseprice_cache'
                          AND column_name='payload'
                    ) THEN
                        ALTER TABLE baseprice_cache ADD COLUMN payload JSONB;
                        -- if payload is added late, make it nullable-safe:
                        -- We'll allow NULL for old rows; new inserts will supply payload.
                    END IF;
                END $$;
            """))

            # 3) Add created_at if missing
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name='baseprice_cache'
                          AND column_name='created_at'
                    ) THEN
                        ALTER TABLE baseprice_cache
                        ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                    END IF;
                END $$;
            """))

            # 4) Index if missing (safe)
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid
                ON baseprice_cache (product_uuid)
            """))

        else:
            # SQLite fallback (local dev)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS baseprice_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_uuid TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid
                ON baseprice_cache (product_uuid)
            """))

    return {"ok": True, "dialect": dialect, "schema": "baseprice_cache ensured"}


def db_ping() -> Dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -------------------------
# Basic service endpoints
# -------------------------
@app.get("/version")
def version():
    return {"service": SERVICE_NAME, "phase": PHASE, "build": BUILD}


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping_route():
    res = db_ping()
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=res)
    return res


@app.post("/db/init")
def db_init():
    try:
        return ensure_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


# -------------------------
# 4over passthrough endpoints
# -------------------------
@app.get("/4over/whoami")
def whoami():
    try:
        data = fourover_get("/whoami")
        return data
    except Exception as e:
        # Return useful info instead of a generic 500
        raise HTTPException(status_code=401, detail={"error": "4over request failed", "message": str(e)})


# -------------------------
# Doorhangers endpoints
# -------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    """
    Fetch live baseprices from 4over for a product UUID.
    """
    try:
        data = fourover_get(f"/printproducts/products/{product_uuid}/baseprices")
        return data
    except Exception as e:
        raise HTTPException(status_code=401, detail={"error": "4over request failed", "message": str(e)})


@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str, db: Session = Depends(get_db)):
    """
    Fetch baseprices from 4over and cache them to DB.
    """
    # Ensure schema exists/migrated before insert
    ensure_schema()

    try:
        payload = fourover_get(f"/printproducts/products/{product_uuid}/baseprices")
    except Exception as e:
        raise HTTPException(status_code=401, detail={"error": "4over request failed", "message": str(e)})

    try:
        dialect = engine.dialect.name

        if dialect == "postgresql":
            stmt = text("""
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, CAST(:payload AS JSONB))
                RETURNING id
            """)
            result = db.execute(stmt, {"product_uuid": product_uuid, "payload": json_dumps(payload)})
            cache_id = result.scalar_one()
            db.commit()
        else:
            # sqlite
            stmt = text("""
                INSERT INTO baseprice_cache (product_uuid, payload)
                VALUES (:product_uuid, :payload)
            """)
            db.execute(stmt, {"product_uuid": product_uuid, "payload": json_dumps(payload)})
            db.commit()
            # last insert id (best effort)
            cache_id = db.execute(text("SELECT last_insert_rowid()")).scalar()

        return {"ok": True, "product_uuid": product_uuid, "cache_id": int(cache_id) if cache_id is not None else None}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail={"error": "db error", "message": str(e)})


# -------------------------
# Cache read endpoints
# -------------------------
@app.get("/cache/baseprices")
def cache_list(limit: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    """
    List most recent cached baseprices rows.
    """
    ensure_schema()

    try:
        stmt = text("""
            SELECT id, product_uuid, payload, created_at
            FROM baseprice_cache
            ORDER BY id DESC
            LIMIT :limit
        """)
        rows = db.execute(stmt, {"limit": limit}).mappings().all()

        # decode payload JSON if needed (sqlite stores text)
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "product_uuid": r["product_uuid"],
                "payload": json_loads(r["payload"]),
                "created_at": str(r["created_at"]),
            })
        return {"ok": True, "count": len(out), "rows": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache list failed", "message": str(e)})


@app.get("/cache/baseprices/{product_uuid}")
def cache_latest(product_uuid: str, db: Session = Depends(get_db)):
    """
    Get the latest cached baseprices payload for a product_uuid.
    """
    ensure_schema()

    try:
        stmt = text("""
            SELECT id, product_uuid, payload, created_at
            FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY id DESC
            LIMIT 1
        """)
        row = db.execute(stmt, {"product_uuid": product_uuid}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not found", "product_uuid": product_uuid})

        return {
            "ok": True,
            "id": row["id"],
            "product_uuid": row["product_uuid"],
            "payload": json_loads(row["payload"]),
            "created_at": str(row["created_at"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "cache fetch failed", "message": str(e)})


# -------------------------
# JSON helpers (avoid adding deps)
# -------------------------
import json

def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

def json_loads(val: Any) -> Any:
    # postgres returns dict already for JSONB in many drivers; sqlite returns text
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (str, bytes)):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val
