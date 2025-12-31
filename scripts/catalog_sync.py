from sqlalchemy.orm import Session
from models import CatalogProduct
from fourover_client import FourOverClient
from catalog_parser import parse_product_row

def pull_catalog_page(offset: int, per_page_requested: int = 200) -> dict:
    """
    Pull a page from /products.
    4over may cap perPage (often 20). We'll detect the actual size by len(items).
    """
    client = FourOverClient()
    payload = client.products(offset=offset, per_page=per_page_requested)

    # Common shapes: payload["items"], payload["data"], etc.
    items = payload.get("items") or payload.get("data") or payload.get("results") or []
    total = payload.get("totalResults") or payload.get("total") or payload.get("count") or None

    return {
        "offset": offset,
        "requested_perPage": per_page_requested,
        "items": items,
        "items_count": len(items),
        "totalResults": total,
        "raw": payload,
    }

def upsert_products(db: Session, items: list[dict]) -> int:
    n = 0
    for row in items:
        parsed = parse_product_row(row)
        if not parsed.get("id"):
            continue

        existing = db.get(CatalogProduct, parsed["id"])
        if existing:
            existing.groupid = parsed["groupid"]
            existing.groupname = parsed["groupname"]
            existing.sizeid = parsed["sizeid"]
            existing.sizename = parsed["sizename"]
            existing.stockid = parsed["stockid"]
            existing.stockname = parsed["stockname"]
            existing.coatingid = parsed["coatingid"]
            existing.coatingname = parsed["coatingname"]
            existing.raw_json = parsed["raw_json"]
        else:
            db.add(CatalogProduct(**parsed))
        n += 1
    return n

def sync_catalog(db: Session, pages: int = 1, start_offset: int = 0) -> dict:
    """
    Pull N pages starting at offset, inserting/upserting into DB.
    Offset advances by the enforced page size we observe (len(items)).
    """
    pulled = 0
    offset = start_offset
    enforced_page_size = None
    total_results = None

    sample_first_ids = []
    sample_last_ids = []

    for i in range(pages):
        page = pull_catalog_page(offset=offset, per_page_requested=200)
        items = page["items"]
        total_results = page["totalResults"] if page["totalResults"] is not None else total_results

        if enforced_page_size is None:
            enforced_page_size = page["items_count"] or 0

        if items:
            ids = []
            for x in items:
                pid = x.get("id") or x.get("productid") or x.get("uuid")
                if pid:
                    ids.append(str(pid))

            if i == 0:
                sample_first_ids = ids[:10]
            sample_last_ids = ids[-10:]

        # Write to DB
        upserted = upsert_products(db, items)
        db.commit()

        pulled += upserted

        # Advance offset by enforced count
        step = page["items_count"] or enforced_page_size or 0
        if step <= 0:
            break
        offset += step

        # Stop if we're at the end
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
        "sample_first_10_ids": sample_first_ids,
        "sample_last_10_ids": sample_last_ids,
    }
