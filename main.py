from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from db import engine
from models import Base
from fourover_client import FourOverClient
from routes_catalog import router as catalog_router
import os

app = FastAPI(title="catdi-4over-connector", version="0.9.0")

# Create tables on boot
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
    for r in app.router.routes:
        if hasattr(r, "path"):
            out.append(r.path)
    return sorted(set(out))

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # show host (mask creds)
        db_url = (os.getenv("DATABASE_URL") or "").strip()
        return {"ok": True, "db": "ok", "db_host": db_url.split("@")[-1] if "@" in db_url else db_url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "db": "failed", "error": str(e)})

@app.get("/4over/whoami")
def whoami():
    """
    Quick auth test.
    """
    try:
        client = FourOverClient()
        data = client.whoami()
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/4over/explore-path")
def explore_path(path: str, offset: int = 0, perPage: int = 20):
    """
    Generic explorer with pagination.
    Example: /4over/explore-path?path=/products&offset=0&perPage=20
    """
    try:
        client = FourOverClient()
        data = client.explore_path(path, offset=offset, per_page=perPage)
        return {"ok": True, "path": path, "offset": offset, "perPage": perPage, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# Catalog routes
app.include_router(catalog_router)
