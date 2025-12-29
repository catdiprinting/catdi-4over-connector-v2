import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.8")


def get_client() -> FourOverClient:
    try:
        return FourOverClient()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_list(payload):
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("entities", "data", "items", "results", "categories", "products"):
        v = payload.get(key)
        if isinstance(v, list):
            return v

    for key in ("data", "result"):
        v = payload.get(key)
        if isinstance(v, dict):
            for k2 in ("entities", "items", "results"):
                vv = v.get(k2)
                if isinstance(vv, list):
                    return vv
    return []


def _delta_params(lastupdate: str | None, time: str | None):
    if not lastupdate:
        lastupdate = "2014-01-01"
    if not time:
        time = "00:00:00"
    return {"lastupdate": lastupdate, "time": time}


def _cat_id(item: dict):
    return item.get("category_uuid") or item.get("uuid") or item.get("id")


def _safe_str(x):
    return (str(x) if x is not None else "").strip()


def _fetch(client: FourOverClient, path: str, params: dict):
    resp = client.request("GET", path, params=params)
    payload = resp.get("data", {})
    items = _normalize_list(payload)
    meta = {}
    if isinstance(payload, dict):
        meta = {
            "currentPage": payload.get("currentPage"),
            "maximumPages": payload.get("maximumPages"),
            "totalResults": payload.get("totalResults"),
        }
    return resp, payload, items, meta


def fetch_all_with_offset(client: FourOverClient, path: str, base_params: dict, per_page: int, max_pages: int = 500):
    """
    Correct paging for 4over printproducts feeds:
    uses offset as record offset and perPage as size.
    offset=page*perPage
    """
    seen = {}
    total_results = None
    maximum_pages = None
    pages_fetched = 0

    for page in range(max_pages):
        p = dict(base_params)
        p["perPage"] = per_page
        p["offset"] = page * per_page

        _, payload, items, meta = _fetch(client, path, p)
        pages_fetched += 1

        # Update totals
        if isinstance(meta.get("totalResults"), int):
            total_results = meta["totalResults"]
        if isinstance(meta.get("maximumPages"), int):
            maximum_pages = meta["maximumPages"]

        # Dedup by uuid-ish field if present; fallback to hash of dict
        for it in items:
            if isinstance(it, dict):
                iid = (
                    it.get("product_uuid")
                    or it.get("category_uuid")
                    or it.get("uuid")
                    or it.get("id")
                    or hash(str(it))
                )
                if iid not in seen:
                    seen[iid] = it

        if isinstance(total_results, int) and len(seen) >= total_results:
            break

        if not items:
            break

    return {
        "ok": True,
        "path": path,
        "per_page": per_page,
        "paging": "offset/perPage",
        "meta": {
            "totalResults": total_results,
            "maximumPages": maximum_pages,
            "pages_fetched": pages_fetched,
            "unique_count": len(seen),
        },
        "items": list(seen.values()),
    }


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.8"}


@app.get("/4over/printproducts/categories/all")
def categories_all(lastupdate: str | None = None, time: str | None = None, per_page: int = 20):
    client = get_client()
    params = _delta_params(lastupdate, time)

    result = fetch_all_with_offset(client, "/printproducts/categories", params, per_page=per_page)
    # categories unique id is category_uuid
    cats = result["items"]

    # Re-dedup strictly by category_uuid
    by_uuid = {}
    for c in cats:
        if not isinstance(c, dict):
            continue
        cid = _cat_id(c)
        if cid and cid not in by_uuid:
            by_uuid[cid] = c

    result["meta"]["unique_count"] = len(by_uuid)
    result["items"] = list(by_uuid.values())
    result["sample"] = result["items"][:10]
    return result


@app.get("/4over/categories/search")
def categories_search(q: str, lastupdate: str | None = None, time: str | None = None):
    """
    Searches *category names/descriptions* in the printproducts feed.
    If postcards/flyers/folders aren’t categories, this will show that quickly.
    """
    client = get_client()
    params = _delta_params(lastupdate, time)
    cats = fetch_all_with_offset(client, "/printproducts/categories", params, per_page=50)["items"]

    ql = q.lower().strip()
    matches = []
    for c in cats:
        if not isinstance(c, dict):
            continue
        name = _safe_str(c.get("category_name") or c.get("name"))
        desc = _safe_str(c.get("category_description") or c.get("description"))
        if ql in name.lower() or ql in desc.lower():
            matches.append(c)

    # strict dedupe by uuid
    by_uuid = {}
    for c in matches:
        cid = _cat_id(c)
        if cid and cid not in by_uuid:
            by_uuid[cid] = c

    return {"ok": True, "q": q, "match_count": len(by_uuid), "matches": list(by_uuid.values())[:50]}


@app.get("/4over/productsfeed/search")
def productsfeed_search(q: str, lastupdate: str | None = None, time: str | None = None, per_page: int = 100):
    """
    Docs mention: /printproducts/productsfeed?lastupdate&time
    This endpoint is where products often exist even if categories don’t show the marketing names.
    We pull the feed (paged) then filter by keyword on common fields.
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    feed = fetch_all_with_offset(client, "/printproducts/productsfeed", params, per_page=per_page, max_pages=200)
    items = feed["items"]

    ql = q.lower().strip()
    hits = []
    for p in items:
        if not isinstance(p, dict):
            continue
        hay = " ".join(
            [
                _safe_str(p.get("product_name")),
                _safe_str(p.get("name")),
                _safe_str(p.get("product_description")),
                _safe_str(p.get("description")),
                _safe_str(p.get("category_name")),
                _safe_str(p.get("category_description")),
                _safe_str(p.get("product_code")),
                _safe_str(p.get("sku")),
            ]
        ).lower()

        if ql in hay:
            hits.append(p)

    return {
        "ok": True,
        "q": q,
        "feed_meta": feed["meta"],
        "hits_count": len(hits),
        "hits_sample": hits[:10],
        "note": "If hits_count > 0 for 'postcard'/'folder', those items exist in productsfeed even if the category list is branded differently."
    }


@app.get("/4over/catalog/coverage")
def catalog_coverage(lastupdate: str | None = None, time: str | None = None):
    """
    Quick reality check: do these product families exist in productsfeed?
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    feed = fetch_all_with_offset(client, "/printproducts/productsfeed", params, per_page=200, max_pages=50)
    items = feed["items"]

    keywords = ["postcard", "flyer", "folder", "brochure", "sticker", "rack card", "door hanger"]
    results = {}

    for kw in keywords:
        ql = kw.lower()
        found = 0
        for p in items:
            if not isinstance(p, dict):
                continue
            hay = " ".join(
                [
                    _safe_str(p.get("product_name")),
                    _safe_str(p.get("name")),
                    _safe_str(p.get("product_description")),
                    _safe_str(p.get("description")),
                    _safe_str(p.get("category_name")),
                    _safe_str(p.get("product_code")),
                    _safe_str(p.get("sku")),
                ]
            ).lower()
            if ql in hay:
                found += 1
                if found >= 3:
                    break
        results[kw] = {"found_examples": found}

    return {"ok": True, "feed_meta": feed["meta"], "coverage": results}
