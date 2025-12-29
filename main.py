from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from db import engine, get_db, DATABASE_URL
from models import Base
from fourover_client import FourOverClient
from routes_catalog import router as catalog_router
import os

app = FastAPI(title="Catdi × 4over Connector", version="0.9.0")

# Create tables on startup
Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "ok": True}

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "version": app.version}

@app.get("/routes")
def routes():
    out = []
    for r in app.routes:
        if getattr(r, "methods", None):
            out.append({"path": r.path, "methods": sorted(list(r.methods))})
    return {"ok": True, "routes": out}

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok", "db_host": DATABASE_URL.split("@")[-1]}
    except Exception as e:
        return {"ok": False, "db": "failed", "error": str(e)}

@app.get("/debug/env")
def debug_env():
    # DO NOT leak secrets; only show which keys are present
    keys = [
        "DATABASE_URL",
        "FOUR_OVER_APIKEY", "FOUR_OVER_API_KEY", "FOUROVER_APIKEY", "FOUROVER_API_KEY",
        "FOUR_OVER_PRIVATE_KEY", "FOUROVER_PRIVATE_KEY",
        "FOUR_OVER_BASE_URL", "FOUROVER_BASE_URL",
    ]
    present = {}
    for k in keys:
        v = os.getenv(k)
        present[k] = bool(v and v.strip())
    return {"ok": True, "present": present}

@app.get("/4over/whoami")
def debug_whoami():
    client = FourOverClient()
    return client.whoami()

# Catalog routes
app.include_router(catalog_router)
