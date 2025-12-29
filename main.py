import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.9")


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


def fetch_page_offset(client: FourOverClient, path: str, base_params: dict, offset: int, per_page: int):
    """
    Fetch exactly ONE page using 4over's offset/perPage paging.
    """
    p = dict(base_params)
    p["offset"] = offset
    p["perPage"] = per_page
    resp = client.request("GET", path, params=p)
    payload = resp.get("data", {})
    items = _normalize_list(payload)

    meta = {}
    if isinstance(payload, dict):
        meta = {
            "totalResults": payload.get("totalResults"),
            "maximumPages": payload.get("maximumPages"),
            "currentPage": payload.get("currentPage"),
            "currentPageType": type(payload.get("currentPage")).__name__,
        }

    return {
        **resp,
        "paging": {"offset": offset, "perPage": per_page},
        "meta": meta,
        "items_count": len(items),
        "items_sample": items[:5],
    }


def fetch_all_categories_unique(client: FourOverClient, base_params: dict, per_page: int, max_pages: int = 50):
    """
    Pull all categories safely with offset stepping.
    """
    seen = {}
    total_results = None
    maximum_pages = None
    pages_fetched = 0

    for page in range(max_pages):
        offset = page * per_page
        out = fetch_page_offset(client, "/printproducts/categories", base_params, offset=offset, per_page=per_page)
        payload = out.get("data", {})
        items = _normalize_list(payload)

        pages_fetched += 1

        if isinstance(payload, dict):
            if isinstance(payload.get("totalResults"), int):
                total_results = payload.get("totalResults")
            if isinstance(payload.get("maximumPages"), int):
                maximum_pages = payload.get("maximumPages")

        for c in items:
            if not isinstance(c, dict):
                continue
            cid = _cat_id(c)
            if cid and cid not in seen:
                seen[cid] = c

        if isinstance(total_results, int) and len(seen) >= total_results:
            break

        if not items:
            break

    return {
        "ok": True,
        "paging_param_used": "offset",
        "page_size_param_used": "perPage",
        "per_page": per_page,
        "meta": {
            "totalResults": total_results,
            "maximumPages": maximum_pages,
            "pages_fetched": pages_fetched,
            "unique_count": len(seen),
        },
        "sample": list(seen.values())[:10],
        "items": list(seen.values()),
    }


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "phase": "0.8.9", "build": "safe-productsfeed-enabled"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.9"}


@app.get("/debug/config")
def debug_config():
    db_url = os.getenv("DATABASE_URL", "")
    return {
        "has_FOUR_OVER_APIKEY": bool(os.getenv("FOUR_OVER_APIKEY")),
        "has_FOUR_OVER_PRIVATE_KEY": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_BASE_URL": os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        "db_url_present": bool(db_url),
        "db_is_sqlite": db_url.startswith("sqlite"),
        "db_scheme": (db_url.split(":", 1)[0] if db_url else None),
    }


@app.get("/4over/whoami")
def fourover_whoami():
    client = get_client()
    return client.request("GET", "/whoami")


# ✅ Categories (complete)
@app.get("/4over/printproducts/categories/all")
def categories_all(lastupdate: str | None = None, time: str | None = None, per_page: int = 20):
    client = get_client()
    params = _delta_params(lastupdate, time)
    result = fetch_all_categories_unique(client, params, per_page=per_page, max_pages=50)

    # return without the full items list to keep response light
    return {
        "ok": True,
        "paging_param_used": result["paging_param_used"],
        "page_size_param_used": result["page_size_param_used"],
        "per_page": per_page,
        "meta": result["meta"],
        "sample": result["sample"],
    }


# ✅ Products feed: fetch ONE page only (safe)
@app.get("/4over/printproducts/productsfeed/page")
def productsfeed_page(
    lastupdate: str | None = None,
    time: str | None = None,
    offset: int = 0,
    per_page: int = 50,
):
    client = get_client()
    params = _delta_params(lastupdate, time)
    return fetch_page_offset(client, "/printproducts/productsfeed", params, offset=offset, per_page=per_page)


# ✅ Products feed: keyword search (safe scan, limited pages)
@app.get("/4over/printproducts/productsfeed/search")
def productsfeed_search(
    q: str,
    lastupdate: str | None = None,
    time: str | None = None,
    per_page: int = 100,
    max_pages: int = 3,
):
    client = get_client()
    params = _delta_params(lastupdate, time)

    ql = q.lower().strip()
    hits = []
    scanned_items = 0
    pages_fetched = 0
    total_results = None

    for page in range(max_pages):
        offset = page * per_page
        out = fetch_page_offset(client, "/printproducts/productsfeed", params, offset=offset, per_page=per_page)
        payload = out.get("data", {})
        items = _normalize_list(payload)

        pages_fetched += 1
        scanned_items += len(items)

        if isinstance(payload, dict) and isinstance(payload.get("totalResults"), int):
            total_results = payload.get("totalResults")

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
                if len(hits) >= 25:  # cap to keep response light
                    break

        if len(hits) >= 25:
            break

        if not items:
            break

    return {
        "ok": True,
        "q": q,
        "scan": {"per_page": per_page, "max_pages": max_pages, "pages_fetched": pages_fetched, "scanned_items": scanned_items},
        "feed_totalResults": total_results,
        "hits_count": len(hits),
        "hits_sample": hits[:10],
        "note": "Increase max_pages if needed, but keep it small on Railway to avoid timeouts."
    }
