from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import time
import hmac
import hashlib
import requests
import json

from db import SessionLocal
import config

app = FastAPI()

# -----------------------
# DB Dependency
# -----------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------
# Health / Version
# -----------------------
@app.get("/version")
def version():
    return {
        "service": config.SERVICE_NAME,
        "phase": config.PHASE,
        "build": config.BUILD,
    }

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}

# -----------------------
# DB Init (RAW SQL)
# -----------------------
@app.post("/db/init")
def db_init(db: Session = Depends(get_db)):
    # Create table if missing (Postgres + SQLite compatible)
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS baseprice_cache (
            id SERIAL PRIMARY KEY,
            product_uuid TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            payload TEXT NOT NULL
        )
    """))

    # Create index if missing (Postgres)
    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_baseprice_cache_product_uuid ON baseprice_cache (product_uuid)"))
    except Exception:
        # SQLite older versions or weird adapters might not support IF NOT EXISTS for index
        pass

    db.commit()
    return {"ok": True}

# -----------------------
# 4over Signing
# -----------------------
def sign_4over(canonical: str) -> str:
    # canonical MUST start with / and include query string without signature
    if not canonical.startswith("/"):
        canonical = "/" + canonical

    if not config.FOUR_OVER_PRIVATE_KEY:
        raise RuntimeError("FOUR_OVER_PRIVATE_KEY is missing")

    digest = hmac.new(
        config.FOUR_OVER_PRIVATE_KEY.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha1
    ).hexdigest()
    return digest

def four_over_get(path: str, params: dict):
    base = config.FOUR_OVER_BASE_URL
    url = f"{base}{path}"

    # required params
    params = dict(params or {})
    params["apikey"] = config.FOUR_OVER_APIKEY
    params["timestamp"] = str(int(time.time()))

    # canonical string per 4over style: "/path?apikey=...&timestamp=..."
    # IMPORTANT: sort params, exclude signature
    qp = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
    canonical = f"{path}?{qp}"
    signature = sign_4over(canonical)

    params["signature"] = signature

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# -----------------------
# 4over WhoAmI
# -----------------------
@app.get("/4over/whoami")
def whoami():
    data = four_over_get("/whoami", {})
    return data

# -----------------------
# Doorhangers - Baseprices passthru
# -----------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    return four_over_get(f"/printproducts/products/{product_uuid}/baseprices", {})

# -----------------------
# Import to Cache
# -----------------------
@app.post("/doorhangers/import/{product_uuid}")
def import_baseprices(product_uuid: str, db: Session = Depends(get_db)):
    data = four_over_get(f"/printproducts/products/{product_uuid}/baseprices", {})

    payload_str = json.dumps(data)

    db.execute(
        text("""
            INSERT INTO baseprice_cache (product_uuid, created_at, payload)
            VALUES (:product_uuid, :created_at, :payload)
        """),
        {"product_uuid": product_uuid, "created_at": int(time.time()), "payload": payload_str}
    )
    db.commit()

    # return latest row id
    row = db.execute(
        text("""
            SELECT id FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY id DESC
            LIMIT 1
        """),
        {"product_uuid": product_uuid}
    ).first()

    return {"ok": True, "product_uuid": product_uuid, "cache_id": row[0] if row else None}

# -----------------------
# Cache Read
# -----------------------
@app.get("/cache/baseprices")
def list_cached_baseprices(limit: int = 25, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT id, product_uuid, created_at
            FROM baseprice_cache
            ORDER BY id DESC
            LIMIT :limit
        """),
        {"limit": limit}
    ).mappings().all()

    return {"count": len(rows), "entities": [dict(r) for r in rows]}

@app.get("/cache/baseprices/{product_uuid}")
def get_cached_baseprices(product_uuid: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT id, product_uuid, created_at, payload
            FROM baseprice_cache
            WHERE product_uuid = :product_uuid
            ORDER BY id DESC
            LIMIT 1
        """),
        {"product_uuid": product_uuid}
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No cache found for that product_uuid")

    out = dict(row)
    try:
        out["payload"] = json.loads(out["payload"])
    except Exception:
        pass

    return out
