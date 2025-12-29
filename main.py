from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from db import Base, engine, get_db
from models import ProductFeedItem
from fourover_client import get_client_from_env
from catalog_sync import paging_test_productsfeed, sync_productsfeed

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.8.0",
    "build": "productsfeed-sync",
}

app = FastAPI(title="Catdi 4over Connector", version=APP_VERSION["phase"])

# Create tables on boot
Base.metadata.create_all(bind=engine)


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
