import os
from collections import Counter
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.9.0")


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


def _safe_str(x):
    return (str(x) if x is not None else "").strip()


def fetch_productsfeed_page(client: FourOverClient, base_params: dict, offset: int, per_page: int, size_param: str):
    """
    Fetch exactly one productsfeed page using offset + a chosen size param.
    """
    p = dict(base_params)
    p["offset"] = offset
    p[size_param] = per_page

    resp = client.request("GET", "/printproducts/productsfeed", params=p)
    payload = resp.get("data", {})
    items = _normalize_list(payload)

    meta = {}
    if isinstance(payload, dict):
        meta = {
            "totalResults": payload.get("totalResults"),
            "maximumPages": payload.get("maximumPages"),
            "currentPage": payload.get("currentPage"),
        }

    return {"resp": resp, "payload": payload, "items": items, "meta": meta, "params_used": p}


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.9.0"}


@app.get("/4over/printproducts/productsfeed/inspect")
def productsfeed_inspect(
    lastupdate: str | None = None,
    time: str | None = None,
    offset: int = 0,
    per_page: int = 100,
):
    """
    Inspect how productsfeed responds to page-size params.
    Tries both perPage and limit so we can see which one actually changes items_count.
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    a = fetch_productsfeed_page(client, params, offset=offset, per_page=per_page, size_param="perPage")
    b = fetch_productsfeed_page(client, params, offset=offset, per_page=per_page, size_param="limit")

    return {
        "ok": True,
        "request": {"offset": offset, "per_page_requested": per_page},
        "perPage": {
            "items_count": len(a["items"]),
            "meta": a["meta"],
            "first_product_sample": a["items"][:1],
        },
        "limit": {
            "items_count": len(b["items"]),
            "meta": b["meta"],
            "first_product_sample": b["items"][:1],
        },
        "note": "Whichever returns the larger items_count (or changes behavior) is the page-size param we’ll use."
    }


@app.get("/4over/printproducts/productsfeed/search-smart")
def productsfeed_search_smart(
    q: str,
    lastupdate: str | None = None,
    time: str | None = None,
    per_page: int = 100,
    max_pages: int = 10,
):
    """
    Smart search:
    - auto-detect size param (perPage vs limit) based on which returns more items
    - scan limited pages safely
    - return hits + top category_name counts from scanned sample
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    # detect size param at offset 0
    test_per = fetch_productsfeed_page(client, params, offset=0, per_page=per_page, size_param="perPage")
    test_lim = fetch_productsfeed_page(client, params, offset=0, per_page=per_page, size_param="limit")
    size_param = "perPage" if len(test_per["items"]) >= len(test_lim["items"]) else "limit"

    ql = q.lower().strip()
    hits = []
    scanned_items = 0
    pages_fetched = 0
    total_results = None
    cat_counter = Counter()

    for page in range(max_pages):
        offset = page * (len(test_per["items"]) if size_param == "perPage" else len(test_lim["items"]) or per_page)
        out = fetch_productsfeed_page(client, params, offset=offset, per_page=per_page, size_param=size_param)

        payload = out["payload"]
        items = out["items"]
        meta = out["meta"]

        pages_fetched += 1
        scanned_items += len(items)

        if isinstance(meta.get("totalResults"), int):
            total_results = meta["totalResults"]

        for p in items:
            if not isinstance(p, dict):
                continue

            # category names help us understand what the feed calls things
            cat_name = _safe_str(p.get("category_name") or p.get("category") or "")
            if cat_name:
                cat_counter[cat_name] += 1

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
                if len(hits) >= 20:
                    break

        if len(hits) >= 20:
            break
        if not items:
            break

    return {
        "ok": True,
        "q": q,
        "size_param_used": size_param,
        "scan": {"per_page_requested": per_page, "max_pages": max_pages, "pages_fetched": pages_fetched, "scanned_items": scanned_items},
        "feed_totalResults": total_results,
        "hits_count": len(hits),
        "hits_sample": hits[:10],
        "top_category_names_in_sample": cat_counter.most_common(15),
        "note": "If hits=0, use top_category_names_in_sample to identify correct terminology, then search those terms."
    }
@app.get("/4over/printproducts/productsfeed/paging-test")
def productsfeed_paging_test(
    lastupdate: str | None = None,
    time: str | None = None,
):
    """
    Definitive paging test:
    - Fetch page 0 and page 1 using offset
    - Detect enforced page size
    - Confirm offset increments correctly
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    # Page 0
    p0 = dict(params)
    p0["offset"] = 0
    p0["perPage"] = 200  # intentionally high to test cap

    r0 = client.request("GET", "/printproducts/productsfeed", params=p0)
    data0 = r0.get("data", {})
    items0 = _normalize_list(data0)

    # Page 1 (offset += returned count)
    enforced_page_size = len(items0)
    p1 = dict(params)
    p1["offset"] = enforced_page_size
    p1["perPage"] = 200

    r1 = client.request("GET", "/printproducts/productsfeed", params=p1)
    data1 = r1.get("data", {})
    items1 = _normalize_list(data1)

    return {
        "ok": True,
        "observations": {
            "requested_perPage": 200,
            "enforced_page_size": enforced_page_size,
            "totalResults": data0.get("totalResults"),
            "currentPage_page0": data0.get("currentPage"),
            "currentPage_page1": data1.get("currentPage"),
        },
        "page0": {
            "offset": 0,
            "items_count": len(items0),
            "first_ids": [
                i.get("product_uuid") or i.get("uuid") or i.get("id")
                for i in items0[:5]
            ],
        },
        "page1": {
            "offset": enforced_page_size,
            "items_count": len(items1),
            "first_ids": [
                i.get("product_uuid") or i.get("uuid") or i.get("id")
                for i in items1[:5]
            ],
        },
        "paging_verdict": {
            "page_size_capped": enforced_page_size < 200,
            "offset_moves_forward": items0[:1] != items1[:1],
            "use_this_logic": "offset += enforced_page_size until offset >= totalResults"
        }
    }
def _productsfeed_page(client, offset: int, lastupdate: str | None = None, time: str | None = None):
    params = _delta_params(lastupdate, time)
    params["offset"] = offset
    params["perPage"] = 20  # hard cap confirmed

    r = client.request("GET", "/printproducts/productsfeed", params=params)
    data = r.get("data", {})
    items = _normalize_list(data)

    total = data.get("totalResults")
    current = data.get("currentPage")  # appears to mirror offset
    return items, total, current


@app.get("/4over/printproducts/productsfeed/pull-pages")
def productsfeed_pull_pages(
    pages: int = 3,
    start_offset: int = 0,
    lastupdate: str | None = None,
    time: str | None = None,
):
    """
    Safe pull: fetch N pages of 20 items each and return IDs so we can verify.
    Does NOT try to pull all 9,519 yet.
    """
    if pages < 1:
        pages = 1
    if pages > 50:
        pages = 50  # safety cap

    client = get_client()

    pulled = 0
    offset = start_offset
    total_results = None
    all_ids: list[str] = []

    for _ in range(pages):
        items, total, current = _productsfeed_page(client, offset, lastupdate, time)
        if total_results is None:
            total_results = total

        # stop if nothing returned
        if not items:
            break

        # collect a few ids (or all in these pages)
        for it in items:
            pid = it.get("product_uuid") or it.get("uuid") or it.get("id")
            if pid:
                all_ids.append(pid)

        pulled += len(items)
        offset += len(items)

        # stop if we hit or passed total
        if total_results is not None and offset >= int(total_results):
            break

    return {
        "ok": True,
        "requested_pages": pages,
        "start_offset": start_offset,
        "page_size_assumed": 20,
        "pulled_items": pulled,
        "end_offset": offset,
        "totalResults": total_results,
        "sample_first_10_ids": all_ids[:10],
        "sample_last_10_ids": all_ids[-10:],
        "verdict": "Looks good if pulled_items == pages*20 (unless near end) and IDs change."
    }
