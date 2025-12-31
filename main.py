from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from db import SessionLocal  # must exist already

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/cache/baseprices")
def list_cached_baseprices(limit: int = 25, db: Session = Depends(get_db)):
    # raw SQL (no ORM assumptions)
    q = text("""
        SELECT id, product_uuid
        FROM baseprice_cache
        ORDER BY id DESC
        LIMIT :limit
    """)
    rows = db.execute(q, {"limit": limit}).mappings().all()

    return {
        "count": len(rows),
        "entities": [dict(r) for r in rows],
    }

@app.get("/cache/baseprices/{product_uuid}")
def get_cached_baseprices(product_uuid: str, db: Session = Depends(get_db)):
    q = text("""
        SELECT *
        FROM baseprice_cache
        WHERE product_uuid = :product_uuid
        ORDER BY id DESC
        LIMIT 1
    """)
    row = db.execute(q, {"product_uuid": product_uuid}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="No cache found for that product_uuid")

    data = dict(row)

    # If your table stores JSON as TEXT, try to auto-parse common fields
    for key in ["payload", "data", "response_json", "json", "entities"]:
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key])
            except Exception:
                pass

    return data
