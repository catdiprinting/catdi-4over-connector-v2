import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.4")


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

    # Sometimes nested like {"data":{"entities":[...]}}
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


def paged_get(client: FourOverClient, path: str, params: dict, max_pages: int = 50):
    """
    Pull all pages until we hit maximumPages or get empty entities.
    API response example includes: totalResults, currentPage, maximumPages.
    """
    all_items = []
    page = 0
    meta = {"totalResults": None, "maximumPages": None, "pages_fetched": 0}

    while page < max_pages:
        p = dict(params)
        p["page"] = page

        resp = client.request("GET", path, params=p)
        payload = resp.get("data", {})

        items = _normalize_list(payload)
        all_items.extend(items)

        meta["pages_fetched"] += 1
        if isinstance(payload, dict):
            meta["totalResults"] = payload.get("totalResults", meta["totalResults"])
            meta["maximumPages"] = payload.get("maximumPages", meta["maximumPages"])

            maximum_pages = payload.get("maximumPages", None)
            current_page = payload.get("currentPage", page)

            # If the API tells us the max pages, stop once we pass it
            if isinstance(maximum_pages, int) and current_page >= maximum_pages - 1:
                break

        # If no items returned, stop
        if not items:
            break

        page += 1

    return all_items, meta


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "phase": "0.8.4", "build": "pagination-enabled"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.4"}


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


@app.get("/4over/printproducts/categories")
def printproducts_categories(lastupdate: str | None = None, time: str | None = None, all_pages: bool = True):
    """
    Fetch categories with pagination.
    Set all_pages=false if you only want page 0.
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    if not all_pages:
        resp = client.request("GET", "/printproducts/categories", params=params)
        items = _normalize_list(resp.get("data"))
        return {**resp, "normalized_count": len(items), "sample": items[:5], "used_params": params}

    items, meta = paged_get(client, "/printproducts/categories", params=params, max_pages=60)
    return {
        "http_status": 200,
        "ok": True,
        "normalized_count": len(items),
        "meta": meta,
        "sample": items[:5],
        "used_params": params,
    }


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def printproducts_category_products(category_uuid: str, lastupdate: str | None = None, time: str | None = None, all_pages: bool = True):
    """
    Fetch products for a category with pagination.
    """
    client = get_client()
    params = _delta_params(lastupdate, time)
    path = f"/printproducts/categories/{category_uuid}/products"

    if not all_pages:
        resp = client.request("GET", path, params=params)
        items = _normalize_list(resp.get("data"))
        return {**resp, "normalized_count": len(items), "sample": items[:5], "used_params": params}

    items, meta = paged_get(client, path, params=params, max_pages=200)
    return {
        "http_status": 200,
        "ok": True,
        "category_uuid": category_uuid,
        "normalized_count": len(items),
        "meta": meta,
        "sample": items[:5],
        "used_params": params,
    }


@app.get("/4over/doorhangers/full")
def doorhangers_full(lastupdate: str | None = None, time: str | None = None):
    """
    1) Pull ALL categories (paged)
    2) Find Door Hangers category_uuid
    3) Pull ALL products for that category (paged)
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    cats, cat_meta = paged_get(client, "/printproducts/categories", params=params, max_pages=60)

    door_cat = None
    for c in cats:
        if not isinstance(c, dict):
            continue
        name = str(c.get("category_name") or c.get("name") or "")
        if name.strip().lower() == "door hangers":
            door_cat = c
            break

    if not door_cat:
        # fallback: contains door/hanger
        for c in cats:
            if not isinstance(c, dict):
                continue
            name = str(c.get("category_name") or c.get("name") or "")
            if "door" in name.lower() or "hanger" in name.lower():
                door_cat = c
                break

    if not door_cat:
        return {
            "ok": False,
            "message": "Door Hangers category not found",
            "categories_count": len(cats),
            "categories_meta": cat_meta,
        }

    category_uuid = door_cat.get("category_uuid") or door_cat.get("uuid") or door_cat.get("id")
    prod_path = f"/printproducts/categories/{category_uuid}/products"
    products, prod_meta = paged_get(client, prod_path, params=params, max_pages=200)

    return {
        "ok": True,
        "category": door_cat,
        "categories_meta": cat_meta,
        "products_count": len(products),
        "products_meta": prod_meta,
        "products_sample": products[:5],
        "note": "Next step: map these products/options into DB tables and generate a clean catalog structure for WooCommerce."
    }
