from fastapi import FastAPI
from sqlalchemy import text

from db import Base, engine
from doorhangers import router as doorhangers_router

app = FastAPI(title="catdi-4over-connector", version="SAFE_AND_STABLE_2025-12-30_DOCS_REVERT")

# Create tables
Base.metadata.create_all(bind=engine)

# Routers
app.include_router(doorhangers_router)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "catdi-4over-connector",
        "phase": "DOORHANGERS_PRICING_TESTER",
        "build": "SAFE_AND_STABLE_2025-12-30_DOCS_REVERT",
    }


@app.get("/db/ping")
def db_ping():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}
