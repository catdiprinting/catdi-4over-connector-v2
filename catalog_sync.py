from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from db import SessionLocal
from models import CatalogItem
from fourover_client import FourOverClient

router = APIRouter()

def get_db() -> Session:
    return SessionLocal()

@router.get("/stats")
def catalog_stats():
    db = get_db()
    try:
        total = db.query(CatalogItem).count()
        return {"ok": True, "catalog_items": total}
    finally:
        db.close()

@router.get("/sample")
def catalog_sample(limit: int = Query(10, ge=1, le=50)):
    db = get_db()
    try:
        rows = db.query(CatalogItem).order_by(CatalogItem.created_at.desc()).limit(limit).all()
        return {
            "ok": True,
            "count": len(rows),
            "items": [
                {
                    "id": r.id,
                    "external_id": r.external_id,
                    "name": r.name,
                    "category": r.category,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }
    finally:
        db.close()

@router.post("/sync")
def catalog_sync(
    pages: int = Query(1, ge=1, le=200),
    start_offset: int = Query(0, ge=0),
):
    """
    Pull catalog items from 4over in pages.
    Uses enforced page size behavior (usually 20) by advancing offset using returned count.
    """
    client = FourOverClient()
    db = get_db()

    pulled = 0
    upserted = 0
    offset = start_offset
    page_size_requested = 200  # request big; API enforces actual page size

    try:
        for _ in range(pages):
            resp = client.get_printproducts(offset=offset, perPage=page_size_requested)

            # Expecting shape like: { "meta": {...}, "data": [ ... ] } or similar
            items = resp.get("data") or resp.get("items") or []
            meta = resp.get("meta") or resp.get("pagination") or {}

            if not isinstance(items, list):
                return {"ok": False, "error": "Unexpected response shape", "resp_keys": list(resp.keys())}

            count = len(items)
            pulled += count

            # Upsert each item
            for it in items:
                external_id = str(it.get("id") or it.get("uuid") or "")
                if not external_id:
                    continue

                name = it.get("name") or it.get("title") or ""
                category = it.get("category") or it.get("category_name") or ""

                existing = db.query(CatalogItem).filter(CatalogItem.external_id == external_id).first()
                if existing:
                    existing.name = name
                    existing.category = category
                else:
                    db.add(CatalogItem(external_id=external_id, name=name, category=category))
                upserted += 1

            db.commit()

            # Advance offset by the ACTUAL returned count (enforced page size)
            if count == 0:
                break
            offset += count

            # optional early stop if totalResults known
            total_results = meta.get("totalResults") or meta.get("total") or None
            if total_results is not None and isinstance(total_results, int) and offset >= total_results:
                break

        return {
            "ok": True,
            "pages_requested": pages,
            "start_offset": start_offset,
            "end_offset": offset,
            "pulled_items": pulled,
            "upserted_items": upserted,
        }

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
