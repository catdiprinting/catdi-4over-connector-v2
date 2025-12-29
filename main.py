from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import traceback

from db import engine, Base, get_db
import catalog_sync

app = FastAPI(title="catdi-4over-connector", version="0.9.1")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "version": "0.9.1"}

@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok"}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}

@app.get("/health/catalog")
def health_catalog():
    return {"ok": True, "catalog_routes_loaded": True}

@app.get("/catalog/stats")
def catalog_stats(db: Session = Depends(get_db)):
    count = catalog_sync.get_catalog_count(db)
    return {"ok": True, "catalog_items": count}

@app.post("/catalog/sync")
def catalog_sync_endpoint(pages: int = 1, start_offset: int = 0, db: Session = Depends(get_db)):
    """
    Writes IDs into DB.
    """
    try:
        return catalog_sync.sync_catalog(db=db, pages=pages, start_offset=start_offset)
    except Exception as e:
        return {
            "ok": False,
            "where": "/catalog/sync",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

@app.get("/catalog/sync/dryrun")
def catalog_sync_dryrun(offset: int = 0):
    """
    Pulls from 4over ONLY (no DB writes) so we can debug 4over quickly.
    """
    try:
        payload = catalog_sync.pull_catalog_page(offset=offset, per_page_requested=200)
        ids = catalog_sync.extract_ids(payload)
        return {
            "ok": True,
            "offset": offset,
            "items_count": len(ids),
            "first_10_ids": ids[:10],
            "keys": list(payload.keys())[:30],
        }
    except Exception as e:
        return {
            "ok": False,
            "where": "/catalog/sync/dryrun",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
