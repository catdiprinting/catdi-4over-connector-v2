import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.3")


def get_client() -> FourOverClient:
    try:
        return FourOverClient()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_list(payload):
    """
    4over responses vary by endpoint:
    sometimes list is payload["entities"], sometimes payload["data"], etc.
    This tries common shapes and returns a list (or []).
    """
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

    # Sometimes payload looks like {"data":{"entities":[...]}}
    for key in ("data", "result"):
        v = payload.get(key)
        if isinstance(v, dict):
            for k2 in ("entities", "items", "results"):
                vv = v.get(k2)
                if isinstance(vv, list):
                    return vv

    return []


def _delta_params(lastupdate: str | None, time: str | None):
    """
    If caller doesn't provide params, use a very old date to force "full pull".
    Docs show lastupdate & time are used for delta syncing.
    """
    if not lastupdate:
        lastupdate = "2014-01-01"
    if not time:
        time = "00:00:00"
    return {"lastupdate": lastupdate, "time": time}


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "phase": "0.8.3", "build": "printproducts-delta-sync-enabled"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.3"}


@app.get("/routes")
def routes():
    return {
        "count": len(app.routes),
        "routes": [
            {"path": r.path, "methods": list(r.methods), "name": r.name}
            for r in app.routes
            if hasattr(r, "methods")
        ],
    }


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
def printproducts_categories(lastupdate: str | None = None, time: str | None = None):
    """
    Docs: /printproducts/categories?lastupdate=YYYY-MM-DD&time=HH:MM:SS
    """
    client = get_client()
    params = _delta_params(lastupdate, time)
    resp = client.request("GET", "/printproducts/categories", params=params)

    items = _normalize_list(resp.get("data"))
    return {
        **resp,
        "normalized_count": len(items),
        "sample": items[:5],
        "used_params": params,
    }


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def printproducts_category_products(category_uuid: str, lastupdate: str | None = None, time: str | None = None):
    """
    Docs: /printproducts/categories/{category_uuid}/products?lastupdate=...&time=...
    """
    client = get_client()
    params = _delta_params(lastupdate, time)
    path = f"/printproducts/categories/{category_uuid}/products"
    resp = client.request("GET", path, params=params)
