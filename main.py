# main.py
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from db import init_db, get_db, CatalogGroup
from fourover_client import FourOverClient

load_dotenv()

APP_NAME = "catdi-4over-connector"
PHASE = "0.6"
BUILD = os.getenv("BUILD", "psycopg3-forced")

FOUROVER_API_KEY = os.getenv("FOUROVER_API_KEY", "")
FOUROVER_PRIVATE_KEY = os.getenv("FOUROVER_PRIVATE_KEY", "")
FOUROVER_BASE_URL = os.getenv("FOUROVER_BASE_URL", "https://api.4over.com")

# Create app
app = FastAPI(title=APP_NAME)

# Create 4over client (lazy-init)
_client: Optional[FourOverClient] = None


def four_over() -> FourOverClient:
    global _client
    if _client is None:
        _client = FourOverClient(
            api_key=FOUROVER_API_KEY,
            private_key=FOUROVER_PRIVATE_KEY,
            base_url=FOUROVER_BASE_URL,
        )
    return _client


@app.on_event("startup")
def startup():
    # Ensure tables exist (Phase 1)
    init_db()


# -------------------
# Core utility routes
# -------------------
@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/routes")
def routes():
    # Useful for verifying deploy is correct
    out = []
    for r in app.router.routes:
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", None)
        name = getattr(r, "name", None)
        if path:
            out.append({"path": path, "methods": sorted(list(methods)) if methods else [], "name": name})
    out = sorted(out, key=lambda x: x["path"])
    return {"count": len(out), "routes": out}


# -------------------
# 4over debug/explore
# -------------------
@app.get("/4over/whoami")
def four_over_whoami():
    try:
        return four_over().whoami()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/explore")
def four_over_explore():
    """
    Safe default explorer landing.
    """
    return {
        "hint": "Use /4over/explore-path?path=/products or /4over/explore-path?path=/products&q=door",
        "examples": [
            "/4over/explore-path?path=/products",
            "/4over/explore-path?path=/products&q=door",
            "/4over/explore-path?path=/whoami",
        ],
    }


@app.get("/4over/explore-path")
def four_over_explore_path(
    path: str = Query(..., description="4over API path starting with / e.g. /products"),
    q: Optional[str] = Query(None, description="Optional 4over 'q' search param"),
    limit: int = Query(50, ge=1, le=500, description="limit for endpoints that support it"),
    offset: int = Query(0, ge=0, description="offset for endpoints that support it"),
):
    try:
        params = {}
        # Only include params that make sense
        if q:
            params["q"] = q
        # Many endpoints accept limit/offset; harmless if ignored, but we keep it explicit
        params["limit"] = limit
        params["offset"] = offset

        return four_over().get(path, params=params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------
# Admin: Phase 1 sync (Groups only)
# -------------------
@app.post("/admin/sync-products")
def admin_sync_products(
    q: str = Query(..., description="Search query to filter 4over /products, e.g. door"),
    limit: int = Query(200, ge=1, le=2000, description="How many product rows to scan from 4over"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Phase 1: Pull a slice of /products and upsert unique groups into catalog_groups.
    This is intentionally small + safe.
    """
    try:
        data = four_over().products(q=q, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"4over fetch failed: {e}")

    # 4over /products often returns a list, or sometimes a dict with items
    rows: List[Dict[str, Any]] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # try common keys
        for key in ("items", "data", "results", "products"):
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break
        if not rows and "0" in data:
            # weird shape fallback
            pass

    if not rows:
        return {"ok": True, "message": "No rows returned from 4over (or unexpected shape).", "saved_groups": 0}

    saved = 0
    seen = set()

    for r in rows:
        groupid = str(r.get("groupid") or "").strip()
        groupname = str(r.get("groupname") or "").strip()

        if not groupid or not groupname:
            continue

        if groupid in seen:
            continue
        seen.add(groupid)

        existing = db.query(CatalogGroup).filter(CatalogGroup.group_uuid == groupid).first()
        if existing:
            # update name if changed (rare)
            if existing.group_name != groupname:
                existing.group_name = groupname
            continue

        sample_product_uuid = str(r.get("productid") or r.get("id") or "").strip() or None
        sample_product_name = str(r.get("productname") or r.get("name") or "").strip() or None

        cg = CatalogGroup(
            group_uuid=groupid,
            group_name=groupname,
            sample_product_uuid=sample_product_uuid,
            sample_product_name=sample_product_name,
        )
        db.add(cg)
        saved += 1

    db.commit()

    return {
        "ok": True,
        "query": q,
        "limit": limit,
        "offset": offset,
        "rows_scanned": len(rows),
        "unique_groups_seen": len(seen),
        "saved_groups": saved,
    }


# -------------------
# Catalog: read-only (Phase 1)
# -------------------
@app.get("/catalog/groups/search")
def catalog_groups_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(
