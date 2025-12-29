import os
import traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import engine, SessionLocal, DATABASE_URL
from models import Base
import catalog_sync
from fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector", version="0.8")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "version": "0.8"}

@app.get("/health/db")
def health_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        host = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        return {"ok": True, "db": "ok", "db_host": host.split("@")[-1]}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "db": "failed", "error": str(e)},
        )

@app.get("/debug/env")
def debug_env():
    # ✅ shows presence only; never leak secrets
    def present(k: str) -> bool:
        v = os.getenv(k)
        return bool(v and v.strip())

    return {
        "ok": True,
        "present": {
            "DATABASE_URL": present("DATABASE_URL"),
            "FOUR_OVER_APIKEY": present("FOUR_OVER_APIKEY"),
            "FOUR_OVER_PRIVATE_KEY": present("FOUR_OVER_PRIVATE_KEY"),
            "FOUR_OVER_BASE_URL": present("FOUR_OVER_BASE_URL"),
        },
        "base_url_value": (os.getenv("FOUR_OVER_BASE_URL") or "").strip() or "https://api.4over.com (default)",
    }

@app.get("/debug/4over/whoami")
def debug_whoami():
    try:
        client = FourOverClient()
        data = client.whoami()
        return {"ok": True, "whoami": data}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e), "traceback": traceback.format_exc()},
        )

@app.get("/catalog/sync/dryrun")
def catalog_sync_dryrun(offset: int = 0):
    try:
        payload = catalog_sync.pull_catalog_page(offset=offset, per_page_requested=200)
        ids = []
        for it in payload["items"][:20]:
            _id = it.get("id") or it.get("uuid") or it.get("product_id")
            if _id:
                ids.append(_id)
        return {
            "ok": True,
            "observations": {
                "requested_perPage": 200,
                "enforced_page_size": payload["enforced_page_size"],
                "totalResults": payload["totalResults"],
                "currentOffset": offset,
            },
            "sample_first_ids": ids[:5],
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "where": "/catalog/sync/dryrun", "error": str(e), "traceback": traceback.format_exc()},
        )

@app.post("/catalog/sync")
def catalog_sync_endpoint(pages: int = 1, start_offset: int = 0):
    db = SessionLocal()
    try:
        result = catalog_sync.sync_catalog(db=db, pages=pages, start_offset=start_offset)
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "where": "/catalog/sync", "error": str(e), "traceback": traceback.format_exc()},
        )
    finally:
        db.close()
