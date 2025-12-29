# main.py
from fastapi import FastAPI
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text

from db import Base, engine, SessionLocal
from models import FourOverProductsFeed
from four_over_client import get_client_from_env


app = FastAPI(title="catdi-4over-connector", version="0.8.0")

# Create tables
Base.metadata.create_all(bind=engine)


# -------------------------
# Helpers
# -------------------------
def _normalize_list(data):
    """
    4over endpoints sometimes return:
      - {"totalResults": X, "items": [...]}
      - {"totalResults": X, "data": [...]}
      - {"data": [...]}
      - [...]
    We'll try to convert to a list of items.
    """
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]
        # sometimes nested "results"
        if isinstance(data.get("results"), list):
            return data["results"]
    return []


def _delta_params(lastupdate: str | None = None, time: str | None = None) -> dict:
    """
    Optional delta filters if 4over supports them on this endpoint.
    If not used, leave blank.
    """
    params = {}
    if lastupdate:
        params["lastupdate"] = lastupdate
    if time:
        params["time"] = time
    return params


def _productsfeed_page(client, offset: int, lastupdate: str | None = None, time: str | None = None):
    params = _delta_params(lastupdate, time)
    params["offset"] = offset
    params["perPage"] = 20  # enforced by API

    r = client.request("GET", "/printproducts/productsfeed", params=params)
    if not r["ok"]:
        return [], None, r

    data = r["data"]

    # Sometimes the useful payload is inside data["data"]
    # Sometimes inside data["data"]["items"]
    # We'll normalize carefully.
    payload = data.get("data", data)

    items = _normalize_list(payload)

    total = None
    if isinstance(payload, dict) and payload.get("totalResults") is not None:
        total = payload.get("totalResults")
    elif isinstance(data, dict) and data.get("totalResults") is not None:
        total = data.get("totalResults")

    return items, int(total) if total is not None else None, r


def _extract_uuid(item: dict) -> str | None:
    return item.get("product_uuid") or item.get("uuid") or item.get("id")


def _upsert_productsfeed_batch(db, items: list[dict]) -> int:
    if not items:
        return 0

    rows = []
    for it in items:
        pid = _extract_uuid(it)
        if not pid:
            continue
        rows.append({"product_uuid": pid, "payload": it})

    if not rows:
        return 0

    dialect = db.bind.dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(FourOverProductsFeed).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FourOverProductsFeed.product_uuid],
            set_={
                "payload": stmt.excluded.payload,
                "updated_at": text("NOW()"),
            },
        )
        db.execute(stmt)
        return len(rows)

    # sqlite / others fallback
    for row in rows:
        db.merge(FourOverProductsFeed(product_uuid=row["product_uuid"], payload=row["payload"]))
    return len(rows)


# -------------------------
# Health / Debug
# -------------------------
@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.8.0", "build": "productsfeed-sync"}


@app.get("/4over/whoami")
def whoami():
    client = get_client_from_env()
    r = client.request("GET", "/whoami", params={})
    return r


# -------------------------
# Paging Test (what you just did)
# -------------------------
@app.get("/4over/printproducts/productsfeed/paging_test")
def paging_test(start_offset: int = 0, pages: int = 5):
    client = get_client_from_env()
    offset = start_offset

    all_ids = []
    total_results = None
    enforced_page_size = 20

    for _ in range(pages):
        items, total, raw = _productsfeed_page(client, offset)
        if not raw["ok"]:
            return {"ok": False, "error": raw, "offset": offset}

        if total_results is None:
            total_results = total

        ids = []
        for it in items:
            pid = _extract_uuid(it)
            if pid:
                ids.append(pid)

        all_ids.extend(ids)
        offset += len(items)

    return {
        "ok": True,
        "requested_pages": pages,
        "start_offset": start_offset,
        "page_size_assumed": enforced_page_size,
        "pulled_items": len(all_ids),
        "end_offset": offset,
        "totalResults": total_results,
        "sample_first_10_ids": all_ids[:10],
        "sample_last_10_ids": all_ids[-10:],
        "verdict": "Looks good if pulled_items == pages*20 (unless near end) and IDs change.",
    }


# -------------------------
# FULL SYNC TO DB
# -------------------------
@app.post("/4over/printproducts/productsfeed/sync")
def productsfeed_sync(
    limit_pages: int | None = None,
    start_offset: int = 0,
    lastupdate: str | None = None,
    time: str | None = None,
    commit_every_pages: int = 10,
):
    """
    Pull the entire 4over productsfeed and upsert into DB.

    - limit_pages: optional safety limit while testing (e.g., 50)
    - start_offset: resume point
    - commit_every_pages: commits every N pages
    """
    client = get_client_from_env()
    db = SessionLocal()

    try:
        offset = start_offset
        total_results = None
        pages_done = 0
        items_upserted = 0

        while True:
            items, total, raw = _productsfeed_page(client, offset, lastupdate, time)
            if not raw["ok"]:
                db.rollback()
                return {"ok": False, "error": raw, "offset": offset, "pages_done": pages_done}

            if total_results is None:
                total_results = total

            if not items:
                break

            items_upserted += _upsert_productsfeed_batch(db, items)

            got = len(items)
            offset += got
            pages_done += 1

            if pages_done % max(1, commit_every_pages) == 0:
                db.commit()

            if total_results is not None and offset >= total_results:
                break
            if limit_pages is not None and pages_done >= limit_pages:
                break

        db.commit()

        return {
            "ok": True,
            "start_offset": start_offset,
            "end_offset": offset,
            "pages_done": pages_done,
            "items_upserted": items_upserted,
            "totalResults": total_results,
            "stopped_because": (
                "limit_pages"
                if limit_pages is not None and pages_done >= limit_pages
                else "completed_or_no_more_items"
            ),
        }

    except Exception as e:
        db.rollback()
        return {"ok": False, "error": str(e), "offset": start_offset, "pages_done": 0}

    finally:
        db.close()


# -------------------------
# DB Quick Checks
# -------------------------
@app.get("/db/productsfeed/count")
def productsfeed_count():
    db = SessionLocal()
    try:
        count = db.query(FourOverProductsFeed).count()
        return {"ok": True, "count": count}
    finally:
        db.close()


@app.get("/db/productsfeed/sample")
def productsfeed_sample(limit: int = 5):
    db = SessionLocal()
    try:
        rows = db.query(FourOverProductsFeed).order_by(FourOverProductsFeed.id.asc()).limit(limit).all()
        return {
            "ok": True,
            "items": [{"product_uuid": r.product_uuid, "payload_keys": list((r.payload or {}).keys())} for r in rows],
        }
    finally:
        db.close()
