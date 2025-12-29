import logging
from fastapi import FastAPI, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from db import Base, engine, get_db
from models import ProductFeedItem
from fourover_client import get_client_from_env
from catalog_sync import paging_test_productsfeed, sync_productsfeed

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.8.1",
    "build": "productsfeed-sync-safe-boot",
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("catdi-4over-connector")

app = FastAPI(title="Catdi 4over Connector", version=APP_VERSION["phase"])


@app.on_event("startup")
def startup():
    # Create tables on startup (not at import time), and don't crash the whole process if DB is momentarily unavailable.
    try:
        Base.metadata.create_all(bind=engine)
        log.info("DB tables ensured.")
    except Exception as e:
        log.exception("DB init failed on startup (app will still run): %s", e)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Prevent "crash loops" by returning a clean JSON error instead of killing the process.
    log.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": str(exc),
            "path": request.url.path,
            "hint": "Check Railway logs for full traceback.",
        },
    )


@app.get("/health")
def health(db: Session = Depends(get_db)):
    # quick DB ping
    try:
        _ = db.query(ProductFeedItem).count()
        return {"ok": True, "service": APP_VERSION["service"], "db": "ok"}
    except Exception as e:
        return {"ok": False, "service": APP_VERSION["service"], "db": "error", "error": str(e)}


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/4over/printproducts/productsfeed/paging_test")
def productsfeed_paging_test(
    pages: int = Query(5, ge=1, le=50),
    perPage: int = Query(200, ge=1, le=1000),
    start_offset: int = Query(0, ge=0),
):
    client = get_client_from_env()
    return paging_test_productsfeed(client=client, pages=pages, per_page_requested=perPage, start_offset=start_offset)


@app.post("/4over/printproducts/productsfeed/sync")
def productsfeed_sync(
    limit_pages: int = Query(10, ge=1, le=500),
    perPage: int = Query(200, ge=1, le=1000),
    start_offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    client = get_client_from_env()
    return sync_productsfeed(
        client=client,
        db=db,
        start_offset=start_offset,
        per_page_requested=perPage,
        limit_pages=limit_pages,
    )


@app.get("/db/productsfeed/count")
def productsfeed_count(db: Session = Depends(get_db)):
    count = db.query(ProductFeedItem).count()
    return {"ok": True, "count": count}
