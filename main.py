import os
import time
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from db import engine, Base, get_db
from fourover import fourover_whoami, fourover_request

APP_PHASE = os.getenv("APP_PHASE", "0.6")
APP_BUILD = os.getenv("APP_BUILD", "get_db_fix_v1")

# Create DB tables (safe if already exist)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="catdi-4over-connector")

@app.get("/")
def root():
    return {
        "service": "catdi-4over-connector",
        "phase": APP_PHASE,
        "build": APP_BUILD,
        "ts": int(time.time()),
    }

@app.get("/version")
def version():
    return {
        "service": "catdi-4over-connector",
        "phase": APP_PHASE,
        "build": APP_BUILD,
    }

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    # Minimal DB check
    db.execute("SELECT 1")
    return {"ok": True}

@app.get("/4over/whoami")
def whoami():
    """
    Calls 4over /whoami using the configured env vars + signature.
    """
    try:
        return fourover_whoami()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"4over whoami failed: {e}")

@app.get("/4over/proxy")
def fourover_proxy(path: str, apikey: str | None = None):
    """
    Simple proxy tester:
      /4over/proxy?path=/printproducts/categories
    """
    try:
        return fourover_request(path=path, params={} , apikey_override=apikey)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"4over proxy failed: {e}")

@app.get("/health")
def health():
    return {"ok": True}
