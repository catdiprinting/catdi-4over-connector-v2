import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.7")


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


def _first_ids(items, n=5):
    out = []
    for it in items[:n]:
        if isinstance(it, dict):
            out.append(_cat_id(it) or it.get("category_name") or it.get("name"))
        else:
            out.append(str(it))
    return out


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


def diagnose_paging_param(client: FourOverClient, path: str, base_params: dict, per_page: int):
    """
    Try different pagination param names, WITH an explicit page size.
    Important: if param is 'offset', offset is record offset (0, per_page, 2*per_page...)
    """
    candidates = ["currentPage", "page", "offset", "pageNumber", "p"]
    size_params_to_try = [{"perPage": per_page}, {"limit": per_page}]

    findings = []
    for size_param in size_params_to_try:
        for param in candidates:
            # page 0
            p0 = dict(base_params)
            p0.update(size_param)
            if param == "offset":
                p0[param] = 0
            else:
                p0[param] = 0

            _, _, items0, meta0 = _fetch(client, path, p0)

            # page 1
            p1 = dict(base_params)
            p1.update(size_param)
            if param == "offset":
                p1[param] = per_page  # <-- KEY FIX: record offset
            else:
                p1[param] = 1

            _, _, items1, meta1 = _fetch(client, path, p1)

            ids_changed = _first_ids(items0) != _first_ids(items1)
            cur_changed = (meta0.get("currentPage") is not None and meta1.get("currentPage") is not None and meta0["currentPage"] != meta1["currentPage"])

            findings.append(
                {
                    "param": param,
                    "size_param_used": list(size_param.keys())[0],
                    "page0_first_ids": _first_ids(items0),
                    "page1_first_ids": _first_ids(items1),
                    "ids_changed": ids_changed,
                    "currentPage0": meta0.get("currentPage"),
                    "currentPage1": meta1.get("currentPage"),
                    "currentPage_changed": cur_changed,
                    "totalResults": meta0.get("totalResults"),
                    "maximumPages": meta0.get("maximumPages"),
                    "items_len_page0": len(items0),
                    "items_len_page1": len(items1),
                }
            )

    # best = one that changes ids and has sane page sizes
    best = None
    for f in findings:
        if f["ids_changed"] and f["items_len_page0"] > 0:
            best = f
            break

    return {"best": best, "findings": findings}


def fetch_all_categories(client: FourOverClient, base_params: dict, per_page: int):
    diag = diagnose_paging_param(client, "/printproducts/categories", base_params, per_page)
    best = diag.get("best")
    if not best:
        return {"ok": False, "message": "Could not detect pagination param", "diagnose": diag}

    paging_param = best["param"]
    size_param_name = best["size_param_used"]

    seen = {}
    total_results = best.get("totalResults")
    maximum_pages = best.get("maximumPages")

    pages_fetched = 0
    for page in range(0, 1000):
        p = dict(base_params)
        # set page size
        if size_param_name == "perPage":
            p["perPage"] = per_page
        else:
            p["limit"] = per_page

        # set paging
        if paging_param == "offset":
            p["offset"] = page * per_page  # <-- KEY FIX
        else:
            p[paging_param] = page

        _, _, items, meta = _fetch(client, "/printproducts/categories", p)
        pages_fetched += 1

        for it in items:
            if not isinstance(it, dict):
                continue
            cid = _cat_id(it)
            if cid and cid not in seen:
                seen[cid] = it

        # refresh totals if present
        if isinstance(meta.get("totalResults"), int):
            total_results = meta["totalResults"]
        if isinstance(meta.get("maximumPages"), int):
            maximum_pages = meta["maximumPages"]

        if isinstance(total_results, int) and len(seen) >= total_results:
            break

        # If endpoint uses maximumPages, we can stop using that too,
        # but offset-based paging might not rely on it.
        if paging_param != "offset" and isinstance(maximum_pages, int) and page >= maximum_pages - 1:
            break

        if not items:
            break

    return {
        "ok": True,
        "paging_param_used": paging_param,
        "page_size_param_used": size_param_name,
        "per_page": per_page,
        "meta": {
            "totalResults": total_results,
            "maximumPages": maximum_pages,
            "pages_fetched": pages_fetched,
            "unique_count": len(seen),
        },
        "sample": list(seen.values())[:10],
        "diagnose_best": best,
    }


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.7"}


@app.get("/4over/printproducts/categories/all")
def categories_all(lastupdate: str | None = None, time: str | None = None, per_page: int = 20):
    client = get_client()
    params = _delta_params(lastupdate, time)
    return fetch_all_categories(client, params, per_page=per_page)
