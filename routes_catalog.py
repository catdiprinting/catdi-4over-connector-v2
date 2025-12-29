from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from db import get_db
import catalog_sync

router = APIRouter(prefix="/catalog", tags=["catalog"])

@router.get("/sync/dryrun")
def sync_dryrun(
    pages: int = Query(1, ge=1, le=50),
    start_offset: int = Query(0, ge=0),
):
    # just prove pagination works without DB writes
    # (still hits 4over)
    payload = catalog_sync.pull_products_page(offset=start_offset, per_page_requested=200)
    items = payload.get("items") or payload.get("data") or []
    if isinstance(items, dict) and "items" in items:
        items = items["items"]

    return {
        "ok": True,
        "start_offset": start_offset,
        "requested_pages": pages,
        "sample_count_this_page": len(items),
        "sample_first_5_ids": [it.get("id") for it in items[:5]],
        "payload_keys": sorted(list(payload.keys())),
    }

@router.post("/sync")
def sync_into_db(
    pages: int = Query(1, ge=1, le=500),
    start_offset: int = Query(0, ge=0),
    per_page_requested: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return catalog_sync.sync_products(
        db=db,
        pages=pages,
        start_offset=start_offset,
        per_page_requested=per_page_requested,
    )
