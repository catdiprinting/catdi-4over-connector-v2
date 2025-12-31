from fastapi import FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

# make sure these imports match YOUR filenames
from db import SessionLocal
from models import BasePriceCache  # adjust name if your model differs

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/cache/baseprices")
def list_cached_baseprices(limit: int = 50, db: Session = next(get_db())):
    rows = db.execute(
        select(BasePriceCache).order_by(BasePriceCache.id.desc()).limit(limit)
    ).scalars().all()

    return {
        "count": len(rows),
        "entities": [
            {
                "id": r.id,
                "product_uuid": r.product_uuid,
                "created_at": getattr(r, "created_at", None),
            }
            for r in rows
        ],
    }

@app.get("/cache/baseprices/{product_uuid}")
def get_cached_baseprices(product_uuid: str, db: Session = next(get_db())):
    row = db.execute(
        select(BasePriceCache).where(BasePriceCache.product_uuid == product_uuid)
    ).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail="No cache found for that product_uuid")

    # assuming you stored the full 4over response in a JSON/text column like row.payload
    payload = getattr(row, "payload", None)
    if payload is None:
        # if your column has a different name, update this
        payload = getattr(row, "data", None)

    return {
        "id": row.id,
        "product_uuid": row.product_uuid,
        "payload": payload,
        "created_at": getattr(row, "created_at", None),
    }
