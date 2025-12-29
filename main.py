# main.py
import os
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from db import init_db, engine
from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "0.8"
BUILD = "catalog-explorer-enabled"

app = FastAPI(title=APP_NAME, version=f"{PHASE} ({BUILD})")


# -------------------------
# Startup
# -------------------------
@app.on_event("startup")
def _startup():
    # Ensure tables exist (safe to call repeatedly)
    init_db()


# -------------------------
# Utility helpers
# -------------------------
def env_present() -> Dict[str, bool]:
    return {
        "FOUR_OVER_APIKEY": bool(os.getenv("FOUR_OVER_APIKEY")),
        "FOUR_OVER_PRIVATE_KEY": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_BASE_URL": bool(os.getenv("FOUR_OVER_BASE_URL")),
        "DATABASE_URL": bool(os.getenv("DATABASE_URL")),
    }


def safe_preview(value: Any, max_len: int = 600) -> Any:
    """
    Return a small preview without dumping massive payloads in responses.
    """
    try:
        s = json.dumps(value)
    except Exception:
        s = str(value)

    if len(s) > max_len:
        return s[:max_len] + f"... (truncated, len={len(s)})"
    return value


def summarize_payload(data: Any) -> Dict[str, Any]:
    """
    Summarize JSON payload: keys, list lengths, sample preview.
    """
    summary: Dict[str, Any] = {"type": type(data).__name__}

    if isinstance(data, dict):
        keys = list(data.keys())
        summary["keys"] = keys[:50]
        # include small previews of top-level keys
        preview: Dict[str, Any] = {}
        for k in keys[:10]:
            v = data.get(k)
            if isinstance(v, list):
                preview[k] = {"type": "list", "len": len(v)}
            elif isinstance(v, dict):
                preview[k] = {"type": "dict", "keys": list(v.keys())[:20]}
            else:
                preview[k] = safe_preview(v, 200)
        summary["preview"] = preview

    elif isinstance(data, list):
        summary["len"] = len(data)
        if len(data) > 0:
            summary["first_item_type"] = type(data[0]).__name__
            summary["first_item_preview"] = safe_preview(data[0], 400)

    else:
        summary["value_preview"] = safe_preview(data, 400)

    return summary


def get_client() -> FourOverClient:
    return FourOverClient(
        base_url=os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com",
        apikey=os.getenv("FOUR_OVER_APIKEY"),
        private_key=os.getenv("FOUR_OVER_PRIVATE_KEY"),
        timeout=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
    )


# -------------------------
# Core routes
# -------------------------
@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/routes")
def routes():
    # Helpful for debugging what is actually deployed
    out = []
    for r in app.routes:
        methods = sorted([m for m in getattr(r, "methods", []) if m not in ("HEAD",)])
        out.append({"path": getattr(r, "path", ""), "methods": methods, "name": getattr(r, "name", "")})
    return {"count": len(out), "routes": sorted(out, key=lambda x: x["path"])}


@app.get("/4over/whoami")
def fourover_whoami():
    client = get_client()
    resp = client.request("GET", "/whoami")
    return JSONResponse(resp, status_code=resp.get("http_status", 200))


# -------------------------
# Smoke test (your working POST)
# -------------------------
@app.post("/admin/sync-products")
def sync_products_smoke():
    # DB check
    db_ok = True
    db_error = None
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1;")
    except Exception as e:
        db_ok = False
        db_error = str(e)

    # 4over check
    fourover_ok = False
    fourover_http_status = None
    fourover_error = None
    try:
        client = get_client()
        r = client.request("GET", "/whoami")
        fourover_http_status = r.get("http_status")
        fourover_ok = bool(r.get("ok"))
        if not fourover_ok:
            fourover_error = safe_preview(r.get("data"))
    except Exception as e:
        fourover_ok = False
        fourover_error = str(e)

    return {
        "ok": True,
        "message": "sync endpoint reached",
        "db_ok": db_ok,
        "db_error": db_error,
        "fourover_ok": fourover_ok,
        "fourover_http_status": fourover_http_status,
        "fourover_error": fourover_error,
        "env_present": env_present(),
    }


# -------------------------
# Catalog Explorer
# -------------------------
CANDIDATE_CATALOG_PATHS: List[str] = [
    # Common patterns seen across vendor APIs (we'll discover the real ones)
    "/catalog",
    "/catalogs",
    "/categories",
    "/category",
    "/products",
    "/product",
    "/product-categories",
    "/product_categories",
    "/productcatalog",
    "/product_catalog",
    "/price",
    "/pricing",
    "/price-table",
    "/price_table",
    "/turnaround",
]


def try_path(client: FourOverClient, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resp = client.request("GET", path, params=params or {})
    return {
        "path": path,
        "http_status": resp.get("http_status"),
        "ok": resp.get("ok"),
        "debug": resp.get("debug"),
        "summary": summarize_payload(resp.get("data")),
        # return a tiny preview (optional) so you can see if it looks promising
        "data_preview": safe_preview(resp.get("data"), 800),
    }


@app.get("/4over/explore")
def fourover_explore(
    limit: int = Query(12, ge=1, le=40),
):
    """
    Tries a fixed allowlist of candidate catalog/product endpoints.
    Returns summaries so we can identify which endpoints are real for your 4over account.
    """
    client = get_client()
    results: List[Dict[str, Any]] = []

    for p in CANDIDATE_CATALOG_PATHS[:limit]:
        try:
            results.append(try_path(client, p))
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})

    # Sort: successes first, then by status
    results.sort(key=lambda x: (not x.get("ok", False), x.get("http_status", 999)))
    return {
        "ok": True,
        "tested": min(limit, len(CANDIDATE_CATALOG_PATHS)),
        "candidates": CANDIDATE_CATALOG_PATHS[:limit],
        "results": results,
    }


@app.get("/4over/explore-path")
def fourover_explore_path(
    path: str = Query(..., description="Path to test, e.g. /products or /catalog/products"),
    q: Optional[str] = Query(None, description="Optional search keyword"),
    page: Optional[int] = Query(None, ge=1),
    per_page: Optional[int] = Query(None, ge=1, le=200),
):
    """
    Tests ONE specific path you want to try.
    Safer than a fully-open proxy: it only does GET and only to your 4over base URL.
    """
    client = get_client()

    params: Dict[str, Any] = {}
    if q:
        # common query param names across APIs
        params["q"] = q
        params["search"] = q
        params["keyword"] = q
        params["query"] = q
    if page:
        params["page"] = page
    if per_page:
        params["per_page"] = per_page
        params["limit"] = per_page

    out = try_path(client, path, params=params)
    return {"ok": True, **out}
