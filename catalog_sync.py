from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from models import CatalogItem


PAGE_SIZE_ASSUMED = 20  # we observed API enforces 20 even if perPage requested is higher


def get_catalog_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(CatalogItem)).scalar_one()


def upsert_ids(db: Session, ids: List[str]) -> int:
    upserted = 0
    for _id in ids:
        existing = db.get(CatalogItem, _id)
        if existing:
            continue
        db.add(CatalogItem(id=_id, raw_json=None))
        upserted += 1
    db.commit()
    return upserted


def pull_catalog_page(offset: int, per_page_requested: int = 200) -> Dict[str, Any]:
    """
    Calls your existing fourover_client.py.
    You said you already have fourover_client.py, so we don't rename it.
    We import lazily to avoid crashing the whole app if env vars are missing.
    """
    from fourover_client import FourOverClient  # MUST exist in your project

    client = FourOverClient()
    # Adjust this method name to match YOUR client if different:
    # It should return a dict with fields including totalResults and items list.
    # Common shape: {"totalResults":..., "items":[{"id":...}, ...]}
    return client.get_catalog(offset=offset, per_page=per_page_requested)


def extract_ids(payload: Dict[str, Any]) -> List[str]:
    items = payload.get("items") or payload.get("data") or []
    ids = []
    for it in items:
        if isinstance(it, dict) and "id" in it:
            ids.append(it["id"])
        elif isinstance(it, str):
            ids.append(it)
    return ids


def sync_catalog(db: Session, pages: int = 1, start_offset: int = 0) -> Dict[str, Any]:
    total_pulled = 0
    total_upserted = 0
    offset = start_offset
    total_results: Optional[int] = None

    for _ in range(pages):
        payload = pull_catalog_page(offset=offset, per_page_requested=200)
        if total_results is None:
            total_results = payload.get("totalResults") or payload.get("total_results") or 0

        ids = extract_ids(payload)
        total_pulled += len(ids)
        total_upserted += upsert_ids(db, ids)

        # move forward by enforced page size
        offset += PAGE_SIZE_ASSUMED

        if total_results and offset >= int(total_results):
            break

    return {
        "ok": True,
        "pages_requested": pages,
        "start_offset": start_offset,
        "end_offset": offset,
        "page_size_assumed": PAGE_SIZE_ASSUMED,
        "pulled_items": total_pulled,
        "upserted_items": total_upserted,
        "totalResults": int(total_results or 0),
    }
