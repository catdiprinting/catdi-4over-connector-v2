import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import engine
from models import Base

# IMPORTANT: this must exist in catalog_sync.py
from catalog_sync import router as catalog_router

app = FastAPI(title="catdi-4over-connector", version="0.7")

# CORS (safe default for testing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create DB tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/health/db")
def health_db():
    # db.py usually exposes a SessionLocal; we can safely do a simple connection test via engine
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        # Show host (helps confirm env is correct)
        db_url = os.getenv("DATABASE_URL", "")
        return {"ok": True, "db": "ok", "db_host": db_url.split("@")[-1] if "@" in db_url else db_url}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}

# Mount catalog routes here
app.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
