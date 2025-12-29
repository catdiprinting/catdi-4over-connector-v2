import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import CatalogItem
from fourover_client import FourOverClient
from catalog_parser import extract_fields


def upsert_catalog_item(db, item_id: str, payload: dict):
    fields = extract_fields(payload)

    existing = db.execute(select(CatalogItem).where(CatalogItem.item_id == item_id)).scalar_one_or_none()
    raw_json = json.dumps(payload, ensure_ascii=False)

    if existing:
        existing.name = fields["name"]
        existing.sku = fields["sku"]
        existing.category = fields["category"]
        existing.status = fields["status"]
        existing.raw_json = raw_json
        return "updated"
    else:
        row = CatalogItem(
            item_id=item_id,
            name=fields["name"],
            sku=fields["sku"],
            category=fields["category"],
            status=fields["status"],
            raw_json=raw_json,
        )
        db.add(row)
        return "inserted"


def sync_catalog(max_pages: int = 5, start_offset: int = 0, perPage: int = 200):
    """
    perPage will be capped by 4over (you observed 20).
    Logic: offset += enforced_page_size until done or max_pages reached.
    """
    client = FourOverClient()
    db = SessionLocal()

    try:
        offset = start_offset
        inserted = 0
        updated = 0
        total_results = None
        enforced_page_size = None

        pages_done = 0

        while True:
            if max_pages is not None and pages_done >= max_pages:
                break

            page = client.list_printproducts(offset=offset, perPage=perPage)

            # 4over response patterns vary; handle common ones:
            data = page.get("data") or page
            items = data.get("items") or data.get("results") or data.get("data") or []
            meta = data.get("meta") or data.get("paging") or data.get("pagination") or {}

            # try to infer totals + page size
            if total_results is None:
                total_results = meta.get("totalResults") or meta.get("total") or data.get("totalResults") or data.get("total")

            if enforced_page_size is None:
                enforced_page_size = meta.get("perPage") or meta.get("pageSize") or len(items) or 20

            if not items:
                break

            # Each item may be summary; use item["id"] then fetch full detail
            for it in items:
                item_id = it.get("id") or it.get("uuid") or it.get("printproduct_id")
                if not item_id:
                    continue

                full = client.get_printproduct(item_id)

                verdict = upsert_catalog_item(db, item_id=item_id, payload=full)
                if verdict == "inserted":
                    inserted += 1
                else:
                    updated += 1

            db.commit()

            pages_done += 1
            offset += int(enforced_page_size)

            if total_results is not None and offset >= int(total_results):
                break

        return {
            "ok": True,
            "inserted": inserted,
            "updated": updated,
            "pages_done": pages_done,
            "end_offset": offset,
            "totalResults": total_results,
            "page_size_assumed": enforced_page_size,
        }

    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()
