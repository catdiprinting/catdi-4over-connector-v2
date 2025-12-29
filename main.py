import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.5")


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


def _item_id(item: dict):
    # categories = category_uuid; products vary
    return (
        item.get("category_uuid")
        or item.get("product_uuid")
        or item.get("uuid")
        or item.get("id")
    )


def paged_get_unique(client: FourOverClient, path: str, params: dict, max_pages: int = 200):
    """
    Robust pagination:
    - try page param as 'page', if ignored switch to 'currentPage'
    - dedupe by uuid to prevent inflated counts
    - stop when no new IDs appear
    """
    seen = set()
    all_unique = []
    raw_count = 0

    meta = {
        "totalResults": None,
        "maximumPages": None,
        "pages_fetched": 0,
        "paging_param_used": None,
        "stopped_reason": None,
    }

    # Try with 'page' first, then 'currentPage'
    for paging_param in ("page", "currentPage"):
        # reset for each strategy
        seen.clear()
        all_unique.clear()
        raw_count = 0
        meta["pages_fetched"] = 0
        meta["paging_param_used"] = paging_param
        meta["stopped_reason"] = None
        meta["totalResults"] = None
        meta["maximumPages"] = None

        for page in range(max_pages):
            p = dict(params)
            p[paging_param] = page

            resp = client.request("GET", path, params=p)
            payload = resp.get("data", {})

            items = _normalize_list(payload)
            raw_count += len(items)
            meta["pages_fetched"] += 1

            if isinstance(payload, dict):
                if meta["totalResults"] is None:
                    meta["totalResults"] = payload.get("totalResults")
                if meta["maximumPages"] is None:
                    meta["maximumPages"] = payload.get("maximumPages")

                # If API tells us max pages, we can cap early
                maxp = payload.get("maximumPages")
                if isinstance(maxp, int) and maxp > 0 and page >= maxp - 1:
                    # still allow dedupe logic below
                    pass

            new_added = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                iid = _item_id(it)
                if not iid:
                    continue
                if iid in seen:
                    continue
                seen.add(iid)
                all_unique.append(it)
                new_added += 1

            # If the endpoint ignores paging, page 1 will look identical → new_added becomes 0
            if page > 0 and new_added == 0:
                meta["stopped_reason"] = "no_new_ids_on_next_page (paging param likely ignored)"
                break

            if not items:
                meta["stopped_reason"] = "empty_page"
                break

            # If API exposes maximumPages, stop once we reach it
            if isinstance(meta["maximumPages"], int) and meta["maximumPages"] > 0 and page >= meta["maximumPages"] - 1:
                meta["stopped_reason"] = "reached_maximumPages"
                break

        # Success condition: we got close to totalResults OR we reached max pages without duplicates
        if meta["totalResults"] is None:
            # If no totalResults, accept the first strategy that returns something
            if len(all_unique) > 0:
                return all_unique, raw_count, meta
        else:
            # If we got a plausible unique count, accept
            if len(all_unique) <= meta["totalResults"] and len(all_unique) > 0:
                return all_unique, raw_count, meta

    return all_unique, raw_count, meta


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "phase": "0.8.5", "build": "pagination-dedupe-fixed"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.5"}


@app.get("/4over/printproducts/categories")
def printproducts_categories(lastupdate: str | None = None, time: str | None = None):
    client = get_client()
    params = _delta_params(lastupdate, time)

    unique_items, raw_count, meta = paged_get_unique(client, "/printproducts/categories", params=params, max_pages=200)

    return {
        "http_status": 200,
        "ok": True,
        "meta": meta,
        "raw_items_count": raw_count,
        "unique_count": len(unique_items),
        "sample": unique_items[:10],
        "used_params": params,
        "note": "unique_count should be ~ totalResults (76). If lower, we’ll adjust the paging param name based on docs."
    }


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def printproducts_category_products(category_uuid: str, lastupdate: str | None = None, time: str | None = None):
    client = get_client()
    params = _delta_params(lastupdate, time)
    path = f"/printproducts/categories/{category_uuid}/products"

    unique_items, raw_count, meta = paged_get_unique(client, path, params=params, max_pages=400)

    return {
        "http_status": 200,
        "ok": True,
        "category_uuid": category_uuid,
        "meta": meta,
        "raw_items_count": raw_count,
        "unique_count": len(unique_items),
        "sample": unique_items[:10],
        "used_params": params,
    }


@app.get("/4over/doorhangers/full")
def doorhangers_full(lastupdate: str | None = None, time: str | None = None):
    client = get_client()
    params = _delta_params(lastupdate, time)

    cats, _, cat_meta = paged_get_unique(client, "/printproducts/categories", params=params, max_pages=200)

    door_cat = None
    for c in cats:
        if not isinstance(c, dict):
            continue
        name = str(c.get("category_name") or c.get("name") or "")
        if name.strip().lower() == "door hangers":
            door_cat = c
            break

    if not door_cat:
        return {
            "ok": False,
            "message": "Door Hangers category not found",
            "unique_categories": len(cats),
            "categories_meta": cat_meta,
        }

    category_uuid = door_cat.get("category_uuid")
    prod_path = f"/printproducts/categories/{category_uuid}/products"
    prods, _, prod_meta = paged_get_unique(client, prod_path, params=params, max_pages=400)

    return {
        "ok": True,
        "category": door_cat,
        "categories_meta": cat_meta,
        "products_meta": prod_meta,
        "products_unique_count": len(prods),
        "products_sample": prods[:10],
    }
