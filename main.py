import os
import logging
from fastapi import FastAPI
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("catdi-4over-connector")

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "port": os.getenv("PORT")}

@app.get("/health/db")
def health_db():
    """
    Lazy-import DB stuff so the app still boots even if db/models are broken.
    """
    try:
        from db import SessionLocal, DATABASE_URL  # lazy import
        safe_db = DATABASE_URL
        if "@" in safe_db:
            safe_db = safe_db.split("@", 1)[1]

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"ok": True, "db": "ok", "db_host": safe_db}
        finally:
            db.close()

    except Exception as e:
        log.exception("DB health check failed")
        return {"ok": False, "db": "failed", "error": str(e)}
