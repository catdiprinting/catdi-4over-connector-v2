from sqlalchemy.orm import Session
from fourover_client import FourOverClient
from models import CatalogItem
from catalog_parser import extract_catalog_fields

def pull_products_page(offset: int, per_page_requested: int = 200) -> dict:
    """
    Pull one page from /products. You observed the API caps perPage to 20.
    """
    client = FourOverClient()
    return client.explore_path("/products", offset=offset, per_page=per_page_requested)

def upsert_items(db: Session, items: list[dict]) -> int:
    inserted_or_updated = 0

    for it in items:
        fields = extract_catalog_fields(it)
        pu = fields.get("product_uuid")
        if not pu:
            continue

        existing = db.query(CatalogItem).filter(CatalogItem.product_uuid == pu).one_or_none()
        if existing:
            # update
            existing.group_id = fields["group_id"]
            existing.group_name = fields["group_name"]
            existing.size_id = fields["size_id"]
            existing.size_name = fields["size_name"]
            existing.stock_id = fields["stock_id"]
            existing.stock_name = fields["stock_name"]
            existing.coating_id = fields["coating_id"]
            existing.coating_name = fields["coating_name"]
            existing.raw_json = fields["raw_json"]
        else:
            db.add(CatalogItem(**fields))
        inserted_or_updated += 1

    db.commit()
    return inserted_or_updated

def sync_products(db: Session, pages: int = 1, start_offset: int = 0, per_page_requested: int = 200) -> dict:
    """
    Safe incremental sync: pulls `pages` pages, each page uses offset += enforced_page_size.
    """
    offset = start_offset
    total_pulled = 0
    total_written = 0
    enforced_page_size = None
    total_results = None

    for _ in range(pages):
        payload = pull_products_page(offset=offset, per_page_requested=per_page_requested)

        # Typical shape: { items: [...], totalResults: N, offset: X, perPage: 20 } (varies)
        items = payload.get("items") or payload.get("data") or []
        if isinstance(items, dict) and "items" in items:
            items = items["items"]

        if total_results is None:
            total_results = payload.get("totalResults") or payload.get("total") or None

        # infer enforced page size
        if enforced_page_size is None:
            enforced_page_size = payload.get("perPage") or payload.get("pageSize") or len(items) or 20

        pulled = len(items)
        total_pulled += pulled

        written = upsert_items(db, items)
        total_written += written

        # move forward
        offset += int(enforced_page_size or 20)

        # stop if we reached the end
        if total_results is not None and offset >= int(total_results):
            break

        # stop if API returned nothing (safety)
        if pulled == 0:
            break

    return {
        "ok": True,
        "start_offset": start_offset,
        "end_offset": offset,
        "pages": pages,
        "enforced_page_size": enforced_page_size,
        "pulled_items": total_pulled,
        "written_items": total_written,
        "totalResults": total_results,
    }
