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
        p["offset"] = page * p*
