from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from db import engine, Base, get_db
import catalog_sync

app = FastAPI(title="catdi-4over-connector", version="0.9")

# Create tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "version": "0.9"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok"}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}


@app.get("/health/catalog")
def health_catalog():
    """
    This route confirms the catalog module can import and is wired.
    If this works, your Not Found issue is solved.
    """
    try:
        # if import succeeded above, we're good
        return {"ok": True, "catalog_routes_loaded": True}
    except Exception as e:
        return {"ok": False, "catalog_routes_loaded": False, "error": str(e)}


@app.get("/catalog/stats")
def catalog_stats(db: Session = Depends(get_db)):
    count = catalog_sync.get_catalog_count(db)
    return {"ok": True, "catalog_items": count}


@app.post("/catalog/sync")
def catalog_sync_endpoint(pages: int = 1, start_offset: int = 0, db: Session = Depends(get_db)):
    """
    Example: POST /catalog/sync?pages=5
    """
    return catalog_sync.sync_catalog(db=db, pages=pages, start_offset=start_offset)
