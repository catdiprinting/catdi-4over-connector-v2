from fastapi import FastAPI, Query
from sqlalchemy import text

from db import engine, Base, SessionLocal
from models import CatalogItem
from catalog_sync import sync_catalog

app = FastAPI(title="catdi-4over-connector", version="0.9")

# Create tables on startup
Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # show sanitized host (avoid creds)
        url = str(engine.url)
        safe = url.split("@")[-1] if "@" in url else url
        return {"ok": True, "db": "ok", "db_host": safe}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}

@app.post("/catalog/sync")
def catalog_sync(
    pages: int = Query(5, ge=1, le=200),
    start_offset: int = Query(0, ge=0),
):
    """
    Runs sync for N pages. Use pages=5 first, then increase.
    """
    result = sync_catalog(max_pages=pages, start_offset=start_offset, perPage=200)
    return result

@app.get("/catalog/stats")
def catalog_stats():
    db = SessionLocal()
    try:
        total = db.query(CatalogItem).count()
        return {"ok": True, "rows": total}
    finally:
        db.close()
