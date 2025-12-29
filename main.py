from fastapi import FastAPI
from sqlalchemy import text

from db import engine
from models import Base

app = FastAPI(title="catdi-4over-connector", version="0.8")

@app.on_event("startup")
def startup():
    # Create tables (won't drop anything)
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "version": "0.8"}

@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok"}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}

# --- Optional: only mount catalog routes if file exists & imports cleanly ---
try:
    from catalog_sync import router as catalog_router
    app.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
except Exception as e:
    # If catalog import breaks, app still boots and you can see why here
    @app.get("/health/catalog")
    def health_catalog():
        return {"ok": False, "catalog_routes_loaded": False, "error": str(e)}
