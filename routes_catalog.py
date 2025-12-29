from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from db import get_db
from models import CatalogProduct
import catalog_sync

router = APIRouter(prefix="/catalog", tags=["catalog"])

@router.post("/sync")
def sync(pages: int = Query(1, ge=1, le=200), start_offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return catalog_sync.sync_catalog(db=db, pages=pages, start_offset=start_offset)

@router.get("/sync/dryrun")
def dryrun(pages: int = Query(1, ge=1, le=20), start_offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    # same as sync but does not write
    pulled = 0
    offset = start_offset
    enforced_page_size = None
    total_results = None
    first_ids = []
    last_ids = []

    for i in range(pages):
        page = catalog_sync.pull_catalog_page(offset=offset, per_page_requested=200)
        items = page["items"]
        total_results = page["totalResults"] if page["totalResults"] is not None else total_results

        if enforced_page_size is None:
            enforced_page_size = page["items_count"] or 0

        ids = []
        for x in items:
            pid = x.get("id") or x.get("productid") or x.get("uuid")
            if pid:
                ids.append(str(pid))

        if i == 0:
            first_ids = ids[:10]
        last_ids = ids[-10:]

        pulled += len(items)

        step = page["items_count"] or enforced_page_size or 0
        if step <= 0:
            break
        offset += step

        if total_results is not None and offset >= int(total_results):
            break

    return {
        "ok": True,
        "requested_pages": pages,
        "start_offset": start_offset,
        "page_size_assumed": enforced_page_size,
        "pulled_items": pulled,
        "end_offset": offset,
        "totalResults": total_results,
        "sample_first_10_ids": first_ids,
        "sample_last_10_ids": last_ids,
        "verdict": "Looks good if pulled_items == pages*page_size_assumed (unless near end) and IDs change."
    }

@router.get("/groups/search")
def search_groups(q: str = Query(..., min_length=1), limit: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    # basic groupname search
    stmt = (
        select(CatalogProduct.groupid, CatalogProduct.groupname)
        .where(CatalogProduct.groupname.ilike(f"%{q}%"))
        .where(CatalogProduct.groupid.is_not(None))
        .group_by(CatalogProduct.groupid, CatalogProduct.groupname)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return {"ok": True, "q": q, "results": [{"groupid": r[0], "groupname": r[1]} for r in rows]}
