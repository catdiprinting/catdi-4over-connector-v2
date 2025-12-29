# main.py
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Query
from sqlalchemy.orm import Session

from db import init_db, get_db, CatalogGroup
from fourover_client import FourOverClient

APP_SERVICE = "catdi-4over-connector"
PHASE = "0.8"
BUILD = "catalog-explorer-enabled"

app = FastAPI(title="Catdi 4over Connector", version=f"{PHASE} - {BUILD}")


@app.on_event("startup")
def _startup():
    init_db()


def _env_present() -> Dict[str, bool]:
    keys = ["FOUR_OVER_APIKEY", "FOUR_OVER_PRIVATE_KEY", "FOUR_OVER_BASE_URL", "DATABASE_URL"]
    return {k: bool(os.getenv(k)) for k in keys}


@app.get("/")
def root():
    return {"service": APP_SERVICE, "phase": PHASE, "build": BUILD}


@app.get("/version")
def version():
    return {"service": APP_SERVICE, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        db_ok = True
        db_error = None
    except Exception as e:
        db_ok = False
        db_error = str(e)

    return {
        "ok": db_ok,
        "db_ok": db_ok,
        "db_error": db_error,
        "env_present": _env_present(),
    }


@app.get("/routes")
def routes():
    # lightweight route listing for debugging
    routes_out = []
    for r in app.routes:
        methods = sorted(list(getattr(r, "methods", []) or []))
        routes_out.append({"path": r.path, "methods": methods, "name": r.name})
    return {"count": len(routes_out), "routes": routes_out}


# -----------------------
# 4over passthrough tools
# -----------------------

@app.get("/4over/whoami")
def fourover_whoami():
    client = FourOverClient()
    return client.request("GET", "/whoami")


@app.get("/4over/explore-path")
def fourover_explore_path(path: str = Query(..., description="Example: /products")):
    client = FourOverClient()
    resp = client.request("GET", path)
    data = resp.get("data")

    # summarize large payloads without exploding the response
    summary: Dict[str, Any] = {"type": type(data).__name__}
    data_preview: Any = None

    try:
        if isinstance(data, list):
            summary["len"] = len(data)
            if data:
                summary["first_item_type"] = type(data[0]).__name__
                summary["first_item_preview"] = str(data[0])[:600]
            data_preview = str(data[:2])[:2500]
        elif isinstance(data, dict):
            summary["keys"] = list(data.keys())[:50]
            summary["preview"] = {k: data.get(k) for k in list(data.keys())[:8]}
            data_preview = {k: data.get(k) for k in list(data.keys())[:25]}
        else:
            data_preview = str(data)[:2500]
    except Exception:
        data_preview = "preview_failed"

    return {
        "ok": resp.get("ok", False),
        "path": path,
        "http_status": resp.get("http_status"),
        "debug": resp.get("debug"),
        "summary": summary,
        "data_preview": data_preview,
    }


@app.get("/4over/explore")
def fourover_explore(limit: int = 20):
    """
    Tries common catalog-ish endpoints and reports which exist.
    """
    client = FourOverClient()
    candidates = [
        "/catalog", "/catalogs", "/categories", "/category",
        "/products", "/product",
        "/product-categories", "/product_categories",
        "/productcatalog", "/product_catalog",
        "/price", "/pricing", "/price-table", "/price_table",
        "/turnaround",
    ][: max(1, min(limit, 50))]

    results = []
    for p in candidates:
        r = client.request("GET", p)
        data = r.get("data")
        summary: Dict[str, Any] = {"type": type(data).__name__}
        if isinstance(data, list):
            summary["len"] = len(data)
            if data:
                summary["first_item_preview"] = str(data[0])[:250]
        elif isinstance(data, dict):
            summary["keys"] = list(data.keys())[:20]
            summary["preview"] = {k: data.get(k) for k in list(data.keys())[:5]}

        results.append({
            "path": p,
            "http_status": r.get("http_status"),
            "ok": r.get("ok"),
            "debug": r.get("debug"),
            "summary": summary,
            "data_preview": (str(data)[:900] if not isinstance(data, dict) else data),
        })

    return {"ok": True, "tested": len(candidates), "candidates": candidates, "results": results}


# -----------------------
# Admin: smoke test
# -----------------------

@app.post("/admin/sync-products")
def sync_products_smoke(db: Session = Depends(get_db)):
    # DB test
    db_ok, db_error = True, None
    try:
        db.execute("SELECT 1")
    except Exception as e:
        db_ok, db_error = False, str(e)

    # 4over test
    fourover_ok, fourover_http_status, fourover_error = True, None, None
    try:
        client = FourOverClient()
        r = client.request("GET", "/whoami")
        fourover_ok = bool(r.get("ok"))
        fourover_http_status = r.get("http_status")
        if not fourover_ok:
            fourover_error = str(r.get("data"))
    except Exception as e:
        fourover_ok, fourover_error = False, str(e)

    return {
        "ok": True,
        "message": "sync endpoint reached",
        "db_ok": db_ok,
        "db_error": db_error,
        "fourover_ok": fourover_ok,
        "fourover_http_status": fourover_http_status,
        "fourover_error": fourover_error,
        "env_present": _env_present(),
    }


# -----------------------
# Admin: build GROUP index (Phase 1)
# -----------------------

@app.post("/admin/build-groups")
def admin_build_groups(
    db: Session = Depends(get_db),
    limit: Optional[int] = Query(None, description="Optional: limit products processed (for quick tests)"),
):
    """
    Pull /products once, extract unique (groupid, groupname) and store to DB.
    """
    client = FourOverClient()
    r = client.request("GET", "/products")

    if not r.get("ok"):
        return {
            "ok": False,
            "message": "4over /products failed",
            "http_status": r.get("http_status"),
            "data": r.get("data"),
            "debug": r.get("debug"),
        }

    products = r.get("data")
    if not isinstance(products, list):
        return {"ok": False, "message": "Unexpected /products response type", "type": type(products).__name__}

    seen = set()
    inserted = 0
    updated = 0
    processed = 0

    for p in products:
        if not isinstance(p, dict):
            continue
        processed += 1
        if limit and processed > limit:
            break

        gid = p.get("groupid")
        gname = p.get("groupname")
        if not gid or not gname:
            continue

        key = (gid, gname)
        if key in seen:
            continue
        seen.add(key)

        existing = db.query(CatalogGroup).filter(CatalogGroup.group_uuid == gid).first()
        if existing:
            if existing.group_name != gname:
                existing.group_name = gname
                updated += 1
        else:
            db.add(CatalogGroup(
                group_uuid=gid,
                group_name=gname,
                sample_product_uuid=p.get("id"),
                sample_product_name=p.get("name"),
            ))
            inserted += 1

    db.commit()

    return {
        "ok": True,
        "message": "groups indexed",
        "processed_products": processed,
        "unique_groups_seen": len(seen),
        "inserted": inserted,
        "updated": updated,
    }


# -----------------------
# Catalog Explorer endpoints (fast UX)
# -----------------------

@app.get("/catalog/groups")
def catalog_groups(db: Session = Depends(get_db), limit: int = 200):
    rows = (
        db.query(CatalogGroup)
        .order_by(CatalogGroup.group_name.asc())
        .limit(max(1, min(limit, 2000)))
        .all()
    )
    return {
        "ok": True,
        "count": len(rows),
        "groups": [
            {
                "groupid": r.group_uuid,
                "groupname": r.group_name,
                "sample_product_uuid": r.sample_product_uuid,
                "sample_product_name": r.sample_product_name,
            }
            for r in rows
        ],
    }


@app.get("/catalog/groups/search")
def catalog_groups_search(
    q: str = Query(..., description="Example: door"),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    qq = f"%{q.strip()}%"
    rows = (
        db.query(CatalogGroup)
        .filter(CatalogGroup.group_name.ilike(qq))
        .order_by(CatalogGroup.group_name.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {
        "ok": True,
        "q": q,
        "count": len(rows),
        "groups": [
            {"groupid": r.group_uuid, "groupname": r.group_name}
            for r in rows
        ],
    }
