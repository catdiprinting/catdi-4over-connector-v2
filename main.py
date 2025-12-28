# main.py
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from db import init_db, get_db
from routes_catalog import router as catalog_router
from catalog_sync import upsert_catalog

import fourover_client  # your existing file

app = FastAPI(title="catdi-4over-connector-v2")

@app.on_event("startup")
def startup():
    init_db()

app.include_router(catalog_router)

@app.get("/health")
def health():
    return {"ok": True}

# ---- Admin: sync the catalog into DB
@app.post("/admin/sync-catalog")
def sync_catalog(db: Session = Depends(get_db)):
    """
    Pull product list from 4over and cache it.
    You can protect this later with a token.
    """
    # You MUST adapt this to your existing client function.
    # Example expectation: fourover_client.list_products() -> list[dict]
    entities = fourover_client.list_products()
    result = upsert_catalog(db, entities)
    return {"ok": True, "synced": result, "count": len(entities)}
