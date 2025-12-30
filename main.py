from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional, Set
import os
import re
import traceback

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import inspect

from fourover_client import FourOverClient
from db import engine, Base, get_db, db_ping
from models import Product, ProductOptionGroup, ProductOptionValue, ProductBasePrice

APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE1"
BUILD = "BASELINE_WHOAMI_WORKING_2025-12-30_SCHEMA_GUARD_CRASH_HARDENED"

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

app = FastAPI(title=APP_NAME)
_client: Optional[FourOverClient] = None

# ---------------------------
# Debug JSON error handler
# ---------------------------
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0") == "1"

@app.exception_handler(Exception)
async def all_exception_handler(request, exc: Exception):
    if DEBUG_ERRORS:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
                "trace": traceback.format_exc(),
                "path": str(request.url),
            },
        )
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal Server Error"})


def four_over() -> FourOverClient:
    global _client
    if _client is None:
        _client = FourOverClient()
    return _client


def _json_or_text(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": (resp.text or "")[:2000]}


def _extract_size_from_desc(desc: str) -> Optional[str]:
    if not desc:
        return None
    m = re.search(r'(\d+(\.\d+)?)"\s*X\s*(\d+(\.\d+)?)"', desc)
    if not m:
        return None
    return f'{m.group(1)}" x {m.group(3)}"'


# ---------------------------
# Schema guard (tester tables only)
# ---------------------------
TESTER_TABLES = [
    "product_option_values",
    "product_option_groups",
    "product_baseprices",
    "products",
]

REQUIRED_COLUMNS: Dict[str, Set[str]] = {
    "products": {"product_uuid", "product_code", "product_description", "categories_path", "optiongroups_path", "baseprices_path"},
    "product_option_groups": {"product_option_group_uuid", "product_uuid", "name", "minoccurs", "maxoccurs"},
    "product_option_values": {"product_option_value_uuid", "product_option_group_uuid", "name", "code", "sort"},
    "product_baseprices": {"product_baseprice_uuid", "product_uuid", "quantity", "turnaround", "price"},
}


def _get_table_columns(table_name: str) -> Set[str]:
    insp = inspect(engine)
    if table_name not in insp.get_table_names():
        return set()
    cols = insp.get_columns(table_name)
    return {c["name"] for c in cols}


def _tester_schema_is_ok() -> bool:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())

    for t in TESTER_TABLES:
        if t not in existing_tables:
            return False

    for t, required in REQUIRED_COLUMNS.items():
        cols = _get_table_columns(t)
        if not required.issubset(cols):
            return False

    return True


def _reset_tester_schema_sql():
    # Drop ONLY tester tables
    with engine.begin() as conn:
        conn.execute(sql_text("DROP TABLE IF EXISTS product_option_values CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS product_option_groups CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS product_baseprices CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS products CASCADE"))

    # Recreate from your existing models.py (tester models)
    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def startup_schema_guard():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    # Reset only if tester schema is wrong
    if not _tester_schema_is_ok():
        _reset_tester_schema_sql()


@app.post("/db/reset_tester_schema")
def reset_tester_schema():
    _reset_tester_schema_sql()
    return {"ok": True, "message": "Tester schema reset (products, option groups, option values, baseprices)."}


# ---------------------------
# Core routes
# ---------------------------
@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}

@app.get("/db/ping")
def db_ping_route():
    try:
        db_ping()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/4over/whoami")
def whoami():
    r, _dbg = four_over().get("/whoami", params={})
    if not r.ok:
        return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
    return r.json()

@app.get("/4over/printproducts/categories")
def categories(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    r, dbg = four_over().get("/printproducts/categories", params={"max": max, "offset": offset})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()

@app.get("/4over/printproducts/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    path = f"/printproducts/categories/{category_uuid}/products"
    r, dbg = four_over().get(path, params={"max": max, "offset": offset})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()

# ---------------------------
# Door Hangers (raw passthrough)
# ---------------------------
@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)

@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
    path = f"/printproducts/products/{product_uuid}/optiongroups"
    r, dbg = four_over().get(path, params={"max": 2000, "offset": 0})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()

@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    path = f"/printproducts/products/{product_uuid}/baseprices"
    r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()

# ---------------------------
# Helpers
# ---------------------------
def _entities(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and "entities" in payload and isinstance(payload["entities"], list):
        return payload["entities"]
    if isinstance(payload, list):
        return payload
    return []

def _dedupe_by_key(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen = {}
    for r in rows:
        k = r.get(key)
        if k and k not in seen:
            seen[k] = r
    return list(seen.values())

# ---------------------------
# Sync (tester tables) — handles your real baseprices shape
# ---------------------------
@app.post("/sync/doorhangers")
def sync_doorhangers(max: int = Query(25, ge=1, le=5000), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    try:
        if not _tester_schema_is_ok():
            _reset_tester_schema_sql()

        cat = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)
        products = _entities(cat)
        if not products:
            return {"ok": True, "message": "No products returned from 4over", "synced_products": 0}

        db.execute(sql_text("TRUNCATE TABLE product_option_values RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE product_option_groups RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE product_baseprices RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE products RESTART IDENTITY CASCADE"))
        db.commit()

        product_rows, pog_rows, pov_rows, pbp_rows = [], [], [], []

        for p in products:
            puid = p.get("product_uuid")
            if not puid:
                continue

            product_rows.append({
                "product_uuid": str(puid),
                "product_code": p.get("product_code"),
                "product_description": p.get("product_description"),
                "categories_path": p.get("product_categories"),
                "optiongroups_path": p.get("product_option_groups"),
                "baseprices_path": p.get("product_base_prices"),
            })

            og = doorhangers_optiongroups(str(puid))
            for g in _entities(og):
                guid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
                if not guid:
                    continue

                pog_rows.append({
                    "product_option_group_uuid": str(guid),
                    "product_uuid": str(puid),
                    "name": g.get("name"),
                    "minoccurs": str(g.get("minoccurs") or ""),
                    "maxoccurs": str(g.get("maxoccurs") or ""),
                })

                values = g.get("values") or g.get("options") or []
                if isinstance(values, list):
                    for v in values:
                        vuid = v.get("product_option_value_uuid") or v.get("option_value_uuid") or v.get("uuid")
                        if not vuid:
                            continue
                        pov_rows.append({
                            "product_option_value_uuid": str(vuid),
                            "product_option_group_uuid": str(guid),
                            "name": v.get("name"),
                            "code": v.get("code"),
                            "sort": v.get("sort") if isinstance(v.get("sort"), int) else None,
                        })

            bp = doorhangers_baseprices(str(puid))
            for b in _entities(bp):
                buid = b.get("base_price_uuid") or b.get("product_baseprice_uuid") or b.get("uuid")
                if not buid:
                    continue

                qty = b.get("quantity") or b.get("runsize")
                try:
                    qty = int(qty) if qty is not None else None
                except Exception:
                    qty = None

                price = b.get("product_baseprice") or b.get("price")
                try:
                    price = float(price) if price is not None else None
                except Exception:
                    price = None

                pbp_rows.append({
                    "product_baseprice_uuid": str(buid),
                    "product_uuid": str(puid),
                    "quantity": qty,
                    "turnaround": b.get("turnaround") or b.get("turn_around_time") or b.get("tat"),
                    "price": price,
                })

        product_rows = _dedupe_by_key(product_rows, "product_uuid")
        pog_rows = _dedupe_by_key(pog_rows, "product_option_group_uuid")
        pov_rows = _dedupe_by_key(pov_rows, "product_option_value_uuid")
        pbp_rows = _dedupe_by_key(pbp_rows, "product_baseprice_uuid")

        if product_rows:
            stmt = pg_insert(Product.__table__).values(product_rows).on_conflict_do_nothing(index_elements=["product_uuid"])
            db.execute(stmt)
        if pog_rows:
            stmt = pg_insert(ProductOptionGroup.__table__).values(pog_rows).on_conflict_do_nothing(index_elements=["product_option_group_uuid"])
            db.execute(stmt)
        if pov_rows:
            stmt = pg_insert(ProductOptionValue.__table__).values(pov_rows).on_conflict_do_nothing(index_elements=["product_option_value_uuid"])
            db.execute(stmt)
        if pbp_rows:
            stmt = pg_insert(ProductBasePrice.__table__).values(pbp_rows).on_conflict_do_nothing(index_elements=["product_baseprice_uuid"])
            db.execute(stmt)

        db.commit()
        return {"ok": True, "synced_products": len(product_rows), "option_groups": len(pog_rows), "option_values": len(pov_rows), "baseprices": len(pbp_rows)}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# Pricing router (SUPER SAFE include)
# ---------------------------
try:
    from pricing_tester import router as pricing_router
    app.include_router(pricing_router)
except Exception as e:
    # never crash on pricing import
    print("[WARN] pricing router not loaded:", repr(e))
