from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func
import traceback

from models import CatalogItem

PAGE_SIZE_ASSUMED = 20  # API enforces 20 even if perPage requested is higher


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
    Calls your existing fourover_client.py lazily so app boot doesn't crash.
    """
    try:
        from fourover_client import FourOverClient  # MUST exist
    except Exception as e:
        raise RuntimeError(
            "Failed importing fourover_client.FourOverClient. "
            "Your fourover_client.py may have a syntax/import/env issue."
        ) from e

    try:
        client = FourOverClient()
    except Exception as e:
        raise RuntimeError(
            "FourOverClient() failed to initialize. "
            "Likely missing env vars (API key/secret) or constructor crash."
        ) from e

    # IMPORTANT: adjust this method name if your client uses something else
    try:
        return client.get_catalog(offset=offset, per_page=per_page_requested)
    except Exception as e:
        raise RuntimeError(
            "client.get_catalog() failed. This is inside your fourover_client call. "
            "Check method name + request auth + response parsing."
        ) from e


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
