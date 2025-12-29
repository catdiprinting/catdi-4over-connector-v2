from sqlalchemy.orm import Session
from sqlalchemy import select
from models import CatalogItem
from fourover_client import FourOverClient
import catalog_parser

def pull_catalog_page(offset: int = 0, per_page_requested: int = 200) -> dict:
    client = FourOverClient()
    payload = client.get_printproducts(offset=offset, per_page=per_page_requested)

    items = catalog_parser.extract_items(payload)
    enforced_page_size = len(items)

    # Try to find "total" in common spots
    total = None
    for k in ("totalResults", "total", "total_results", "count"):
        if isinstance(payload.get(k), int):
            total = payload.get(k)
            break
    if total is None and isinstance(payload.get("paging"), dict) and isinstance(payload["paging"].get("total"), int):
        total = payload["paging"]["total"]

    return {
        "offset": offset,
        "requested_perPage": per_page_requested,
        "enforced_page_size": enforced_page_size,
        "totalResults": total,
        "items": items,
    }

def upsert_items(db: Session, items: list[dict]) -> dict:
    inserted = 0
    updated = 0
    skipped = 0

    for it in items:
        fid = catalog_parser.item_id(it)
        if not fid:
            skipped += 1
            continue

        name = catalog_parser.item_name(it)
        raw = catalog_parser.to_raw_json(it)

        existing = db.execute(
            select(CatalogItem).where(CatalogItem.fourover_id == fid)
        ).scalar_one_or_none()

        if existing:
            existing.name = name
            existing.raw_json = raw
            updated += 1
        else:
            db.add(CatalogItem(fourover_id=fid, name=name, raw_json=raw))
            inserted += 1

    db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}

def sync_catalog(db: Session, pages: int = 1, start_offset: int = 0, per_page_requested: int = 200) -> dict:
    offset = start_offset
    pulled_total = 0
    last_page_size = None
    total_results = None

    for _ in range(pages):
        page = pull_catalog_page(offset=offset, per_page_requested=per_page_requested)
        items = page["items"]
        last_page_size = page["enforced_page_size"]
        total_results = page["totalResults"]

        pulled_total += len(items)
        result = upsert_items(db, items)

        # move forward by the actual enforced page size
        offset += (last_page_size or 0)

        # If nothing came back, stop early
        if last_page_size == 0:
            break

    return {
        "ok": True,
        "pages_requested": pages,
        "start_offset": start_offset,
        "end_offset": offset,
        "pulled_items": pulled_total,
        "last_page_size": last_page_size,
        "totalResults": total_results,
        "db": "updated",
    }
