from sqlalchemy.orm import Session
from models import ProductFeedItem
from fourover_client import FourOverClient
from catalog_parser import extract_items, extract_total_results, get_item_uuid, serialize_item


def upsert_productsfeed_items(db: Session, items: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0

    for item in items:
        uuid = get_item_uuid(item)
        if not uuid:
            skipped += 1
            continue

        raw = serialize_item(item)

        existing = db.query(ProductFeedItem).filter(ProductFeedItem.product_uuid == uuid).one_or_none()
        if existing:
            if existing.raw_json != raw:
                existing.raw_json = raw
                updated += 1
        else:
            db.add(ProductFeedItem(product_uuid=uuid, raw_json=raw))
            created += 1

    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def sync_productsfeed(
    client: FourOverClient,
    db: Session,
    start_offset: int = 0,
    per_page_requested: int = 200,
    limit_pages: int = 10,
) -> dict:
    """
    Pull N pages from productsfeed and upsert into DB.
    Uses enforced page size from returned item count.
    """
    offset = max(0, int(start_offset))
    pages = max(1, int(limit_pages))

    total_results = None
    enforced_page_size = None

    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_pulled = 0

    last_first_ids = []
    last_last_ids = []

    for page_i in range(pages):
        payload = client.get_productsfeed(offset=offset, per_page=per_page_requested)
        items = extract_items(payload)

        if total_results is None:
            total_results = extract_total_results(payload)

        page_count = len(items)
        if enforced_page_size is None:
            enforced_page_size = page_count if page_count > 0 else 20  # fallback

        # capture sample ids for sanity
        ids = []
        for it in items:
            uid = get_item_uuid(it)
            if uid:
                ids.append(uid)

        if page_i == 0:
            last_first_ids = ids[:10]
        last_last_ids = ids[-10:] if len(ids) >= 10 else ids

        res = upsert_productsfeed_items(db, items)
        total_created += res["created"]
        total_updated += res["updated"]
        total_skipped += res["skipped"]
        total_pulled += page_count

        offset += enforced_page_size

        # stop if we hit the end
        if total_results is not None and offset >= total_results:
            break

        # stop if API returns empty
        if page_count == 0:
            break

    return {
        "ok": True,
        "requested_pages": pages,
        "start_offset": start_offset,
        "perPage_requested": per_page_requested,
        "enforced_page_size": enforced_page_size,
        "pulled_items": total_pulled,
        "items_created": total_created,
        "items_updated": total_updated,
        "items_skipped_no_uuid": total_skipped,
        "end_offset": offset,
        "totalResults": total_results,
        "sample_first_10_ids": last_first_ids,
        "sample_last_10_ids": last_last_ids,
    }


def paging_test_productsfeed(
    client: FourOverClient,
    pages: int = 5,
    per_page_requested: int = 200,
    start_offset: int = 0,
) -> dict:
    offset = max(0, int(start_offset))
    pages = max(1, int(pages))

    total_results = None
    enforced_page_size = None
    pulled_items = 0

    sample_first_10 = []
    sample_last_10 = []

    for page_i in range(pages):
        payload = client.get_productsfeed(offset=offset, per_page=per_page_requested)
        items = extract_items(payload)
        if total_results is None:
            total_results = extract_total_results(payload)

        page_count = len(items)
        pulled_items += page_count

        if enforced_page_size is None:
            enforced_page_size = page_count if page_count > 0 else 20

        ids = []
        for it in items:
            uid = get_item_uuid(it)
            if uid:
                ids.append(uid)

        if page_i == 0:
            sample_first_10 = ids[:10]
        sample_last_10 = ids[-10:] if len(ids) >= 10 else ids

        offset += enforced_page_size

        if total_results is not None and offset >= total_results:
            break

        if page_count == 0:
            break

    return {
        "ok": True,
        "requested_pages": pages,
        "start_offset": start_offset,
        "page_size_assumed": enforced_page_size,
        "pulled_items": pulled_items,
        "end_offset": offset,
        "totalResults": total_results,
        "sample_first_10_ids": sample_first_10,
        "sample_last_10_ids": sample_last_10,
        "verdict": "Looks good if pulled_items == pages*page_size_assumed (unless near end) and IDs change.",
    }
