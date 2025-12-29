import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.6")


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

    # nested variants
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


def diagnose_paging_param(client: FourOverClient, path: str, base_params: dict):
    """
    Try different param names for pagination. The correct one will:
    - change response.data.currentPage (often)
    - and/or change the first few UUIDs between page 0 and page 1
    """
    candidates = [
        "currentPage",
        "page",
        "pageNumber",
        "page_number",
        "p",
        "offset",  # sometimes used with limit
    ]

    findings = []
    for param in candidates:
        # page 0
        p0 = dict(base_params)
        p0[param] = 0
        r0 = client.request("GET", path, params=p0)
        d0 = r0.get("data", {})
        items0 = _normalize_list(d0)
        cur0 = d0.get("currentPage") if isinstance(d0, dict) else None

        # page 1
        p1 = dict(base_params)
        p1[param] = 1
        r1 = client.request("GET", path, params=p1)
        d1 = r1.get("data", {})
        items1 = _normalize_list(d1)
        cur1 = d1.get("currentPage") if isinstance(d1, dict) else None

        changed_ids = _first_ids(items0) != _first_ids(items1)
        changed_current_page = (cur0 is not None and cur1 is not None and cur0 != cur1)

        findings.append(
            {
                "param": param,
                "http0": r0.get("http_status"),
                "http1": r1.get("http_status"),
                "ok0": r0.get("ok"),
                "ok1": r1.get("ok"),
                "cur0": cur0,
                "cur1": cur1,
                "first_ids_page0": _first_ids(items0),
                "first_ids_page1": _first_ids(items1),
                "ids_changed": changed_ids,
                "currentPage_changed": changed_current_page,
                "totalResults": d0.get("totalResults") if isinstance(d0, dict) else None,
                "maximumPages": d0.get("maximumPages") if isinstance(d0, dict) else None,
            }
        )

    # pick best
    best = None
    for f in findings:
        if f["currentPage_changed"] or f["ids_changed"]:
            best = f
            break

    return {"best": best, "findings": findings}


def paged_categories(client: FourOverClient, base_params: dict, paging_param: str, max_pages: int = 500):
    """
    Fetch all pages using the correct paging param. Stop when:
    - unique ids reach totalResults
    - or we hit maximumPages
    """
    seen = {}
    page = 0
    total_results = None
    maximum_pages = None

    while page < max_pages:
        p = dict(base_params)
        p[paging_param] = page
        resp = client.request("GET", "/printproducts/categories", params=p)
        payload = resp.get("data", {})

        if isinstance(payload, dict):
            if total_results is None:
                total_results = payload.get("totalResults")
            if maximum_pages is None:
                maximum_pages = payload.get("maximumPages")

        items = _normalize_list(payload)
        for it in items:
            if not isinstance(it, dict):
                continue
            cid = _cat_id(it)
            if cid and cid not in seen:
                seen[cid] = it

        # stopping rules
        if isinstance(total_results, int) and len(seen) >= total_results:
            break
        if isinstance(maximum_pages, int) and page >= maximum_pages - 1:
            break
        if not items:
            break

        page += 1

    return {
        "unique_count": len(seen),
        "unique_items": list(seen.values()),
        "totalResults": total_results,
        "maximumPages": maximum_pages,
        "pages_fetched": page + 1,
        "paging_param_used": paging_param,
    }


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.6"}


@app.get("/4over/printproducts/categories/diagnose")
def categories_diagnose(lastupdate: str | None = None, time: str | None = None):
    client = get_client()
    params = _delta_params(lastupdate, time)
    return diagnose_paging_param(client, "/printproducts/categories", params)


@app.get("/4over/printproducts/categories/all")
def categories_all(lastupdate: str | None = None, time: str | None = None):
    """
    1) Diagnose paging param
    2) Pull all categories using the correct param
    """
    client = get_client()
    params = _delta_params(lastupdate, time)

    diag = diagnose_paging_param(client, "/printproducts/categories", params)
    best = diag.get("best")
    if not best:
        return {
            "ok": False,
            "message": "Could not detect pagination param. See findings.",
            "diagnose": diag,
        }

    paging_param = best["param"]
    result = paged_categories(client, params, paging_param=paging_param, max_pages=500)

    return {
        "ok": True,
        "paging_param_used": paging_param,
        "meta": {
            "totalResults": result["totalResults"],
            "maximumPages": result["maximumPages"],
            "pages_fetched": result["pages_fetched"],
            "unique_count": result["unique_count"],
        },
        "sample": result["unique_items"][:10],
        "diagnose_best": best,
    }
