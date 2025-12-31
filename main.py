# main.py
import json
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import SERVICE_NAME, PHASE, BUILD
from db import Base, engine, get_db
from models import BasePriceCache
from fourover_client import FourOverClient

app = FastAPI(title="Catdi × 4over Connector", version=PHASE)

@app.get("/version")
def version():
    return {"service": SERVICE_NAME, "phase": PHASE, "build": BUILD}

@app.get("/health")
def health():
    # no DB touch - proves the app is running
    return {"ok": True}

@app.post("/db/init")
def db_init():
    # run ONLY when you want to create tables
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB init failed: {str(e)}")

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {str(e)}")

@app.get("/4over/whoami")
def whoami():
    try:
        client = FourOverClient()
        return client.get("/whoami")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    try:
        client = FourOverClient()
        return client.get(f"/printproducts/products/{product_uuid}/baseprices")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str, db: Session = Depends(get_db)):
    # fetch
    try:
        client = FourOverClient()
        payload = client.get(f"/printproducts/products/{product_uuid}/baseprices")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    # store
    try:
        row = db.query(BasePriceCache).filter(BasePriceCache.product_uuid == product_uuid).first()
        if row:
            row.payload_json = json.dumps(payload)
        else:
            row = BasePriceCache(product_uuid=product_uuid, payload_json=json.dumps(payload))
            db.add(row)

        db.commit()
        db.refresh(row)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": row.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB write failed: {str(e)}")
