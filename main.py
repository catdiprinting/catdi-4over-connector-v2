from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional
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
from pricing_tester import router as pricing_router


APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE1"
BUILD = "BASELINE_WHOAMI_WORKING_2025-12-30_SCHEMA_GUARD_V2_KEYMAPS"

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

app = FastAPI(title=APP_NAME)
app.include_router(pricing_router)

_client: Optional[FourOverClient] = None


# ---------------------------
# Debug JSON error handler
# ---------------------------
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0") == "1"


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
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

REQUIRED_COLUMNS = {
    "products": {
        "product_uuid",
        "product_code",
        "product_description",
        "categories_path",
        "optiongroups_path",
        "baseprices_path",
    },
    "product_option_groups": {"product_option_group_uuid", "product_uuid", "name", "minoccurs", "maxoccurs"},
    "product_option_values": {"product_option_value_uuid", "product_option_group_uuid", "name", "code", "sort"},
    "product_baseprices": {"product_baseprice_uuid", "product_uuid", "quantity", "turnaround", "price"},
}


def _get_table_columns(table_name: str) -> set[str]:
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
    """
    Drops ONLY the tester tables and recreates them from SQLAlchemy models.
    Safe because these are your "tester sync" tables.
    """
    with engine.begin() as conn:
        conn.execute(sql_text("DROP TABLE IF EXISTS product_option_values CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS product_option_groups CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS product_baseprices CASCADE"))
        conn.execute(sql_text("DROP TABLE IF EXISTS products CASCADE"))

    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def startup_schema_guard():
    Base.metadata.create_all(bind=engine)
    if not _tester_schema_is_ok():
        _reset_tester_schema_sql()


@app.post("/db/reset_tester_schema")
def reset_tester_schema():
    _reset_tester_schema_sql()
    return {"ok": True, "message": "Tester schema reset (products, option groups, option values, baseprices)."}


# ---------------------------
# Helpers for 4over payloads
# ---------------------------

def _entities(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and "entities" in payload and isinstance(payload["entities"], list):
        return payload["entities"]
    if isinstance(payload, list):
        return payload
    return []


def _dedupe_by_key(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = r.get(key)
        if k and k not in seen:
            seen[k] = r
    return list(seen.values())


def _as_int(x) -> Optional[int]:
    try:
        if x is None or x == "":
            return None
        return int(x)
    except Exception:
        return None


def _as_float(x) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


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
def category_products(
    category_uuid: str,
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    path = f"/printproducts/categories/{category_uuid}/products"
    r, dbg = four_over().get(path, params={"max": max, "offset": offset})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()


# ---------------------------
# Door Hangers: raw endpoints
# ---------------------------

@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)


@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
    # Docs show these are "productoptiongroups" links, but your existing endpoint works with /optiongroups
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
# Runtime Quote helper (the “real commerce” way)
# ---------------------------

@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str,
    colorspec_uuid: str,
    runsize_uuid: str,
    turnaroundtime_uuid: str,
    option_uuids: List[str] = Query(default=[]),
):
    """
    Wrapper for 4over Product Quote:
    GET /printproducts/productquote?product_uuid=...&colorspec_uuid=...&runsize_uuid=...&turnaroundtime_uuid=...&options[]=...
    Returns total_price breakdown from 4over.
    """
    params = {
        "product_uuid": product_uuid,
        "colorspec_uuid": colorspec_uuid,
        "runsize_uuid": runsize_uuid,
        "turnaroundtime_uuid": turnaroundtime_uuid,
    }
    # 4over expects repeated options[] params
    for i, ou in enumerate(option_uuids):
        params[f"options[{i}]"] = ou  # FourOverClient should encode this; if not, we’ll adjust later.

    r, dbg = four_over().get("/printproducts/productquote", params=params)
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()


# ---------------------------
# SYNC: Door Hangers → Postgres (tester tables)
# ---------------------------

@app.post("/sync/doorhangers")
def sync_doorhangers(
    max: int = Query(25, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Minimal tester sync (safe to re-run):
      - Pull Doorhanger products
      - Pull optiongroups + baseprices per product
      - Store in Postgres
    """
    try:
        if not _tester_schema_is_ok():
            _reset_tester_schema_sql()

        cat = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)
        products = _entities(cat)
        if not products:
            return {"ok": True, "message": "No products returned from 4over", "synced_products": 0}

        # wipe tester tables
        db.execute(sql_text("TRUNCATE TABLE product_option_values RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE product_option_groups RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE product_baseprices RESTART IDENTITY CASCADE"))
        db.execute(sql_text("TRUNCATE TABLE products RESTART IDENTITY CASCADE"))
        db.commit()

        product_rows: List[Dict[str, Any]] = []
        pog_rows: List[Dict[str, Any]] = []
        pov_rows: List[Dict[str, Any]] = []
        pbp_rows: List[Dict[str, Any]] = []

        for p in products:
            puid = p.get("product_uuid")
            if not puid:
                continue
            puid = str(puid)

            product_rows.append(
                {
                    "product_uuid": puid,
                    "product_code": p.get("product_code"),
                    "product_description": p.get("product_description"),
                    "categories_path": p.get("product_categories") or p.get("categories"),
                    "optiongroups_path": p.get("product_option_groups"),
                    "baseprices_path": p.get("product_base_prices"),
                }
            )

            # -----------------
            # OPTION GROUPS (KEY FIX)
            # docs show: product_option_group_name + options[] with option_uuid/option_name
            # -----------------
            og_payload = doorhangers_optiongroups(puid)
            og_items = _entities(og_payload)

            for g in og_items:
                guid = (
                    g.get("product_option_group_uuid")
                    or g.get("option_group_uuid")
                    or g.get("product_product_option_group_uuid")
                    or g.get("uuid")
                )
                if not guid:
                    continue
                guid = str(guid)

                gname = g.get("product_option_group_name") or g.get("name") or g.get("product_product_option_group_name")

                pog_rows.append(
                    {
                        "product_option_group_uuid": guid,
                        "product_uuid": puid,
                        "name": gname,
                        "minoccurs": str(g.get("minoccurs") or ""),
                        "maxoccurs": str(g.get("maxoccurs") or ""),
                    }
                )

                # options list (not values)
                options = g.get("options") or g.get("values") or []
                if isinstance(options, list):
                    for v in options:
                        vuid = v.get("option_uuid") or v.get("product_option_value_uuid") or v.get("uuid")
                        if not vuid:
                            continue
                        vuid = str(vuid)

                        vname = v.get("option_name") or v.get("name") or v.get("capi_name")
                        vdesc = v.get("option_description") or v.get("capi_description") or ""

                        pov_rows.append(
                            {
                                "product_option_value_uuid": vuid,
                                "product_option_group_uuid": guid,
                                "name": vname,
                                # keep "code" as a short identifier; option_name is usually the best “code”
                                "code": v.get("code") or v.get("option_code") or vname or vdesc,
                                "sort": _as_int(v.get("sort")),
                            }
                        )

            # -----------------
            # BASE PRICES (DEFENSIVE MAP)
            # docs say baseprices returns runsizes/colorspec combos and can_group_ship
            # We only need enough to test (quantity + turnaround + price).
            # -----------------
            bp_payload = doorhangers_baseprices(puid)
            bp_items = _entities(bp_payload)

            for b in bp_items:
                buid = b.get("product_baseprice_uuid") or b.get("baseprice_uuid") or b.get("uuid")
                if not buid:
                    continue
                buid = str(buid)

                # quantity is typically runsize; sometimes given as runsize or quantity
                qty = (
                    b.get("quantity")
                    or b.get("runsize")
                    or b.get("runsize_qty")
                    or b.get("runsize_quantity")
                )

                # turnaround label/uuid varies by payloads
                tat = (
                    b.get("turnaround")
                    or b.get("turnaround_time")
                    or b.get("turnaroundtime")
                    or b.get("turn_around_time")
                    or b.get("tat")
                )

                # base price field varies
                price = b.get("price") or b.get("base_price") or b.get("baseprice")

                pbp_rows.append(
                    {
                        "product_baseprice_uuid": buid,
                        "product_uuid": puid,
                        "quantity": _as_int(qty),
                        "turnaround": tat,
                        "price": _as_float(price),
                    }
                )

        product_rows = _dedupe_by_key(product_rows, "product_uuid")
        pog_rows = _dedupe_by_key(pog_rows, "product_option_group_uuid")
        pov_rows = _dedupe_by_key(pov_rows, "product_option_value_uuid")
        pbp_rows = _dedupe_by_key(pbp_rows, "product_baseprice_uuid")

        if product_rows:
            stmt = pg_insert(Product.__table__).values(product_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["product_uuid"])
            db.execute(stmt)

        if pog_rows:
            stmt = pg_insert(ProductOptionGroup.__table__).values(pog_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["product_option_group_uuid"])
            db.execute(stmt)

        if pov_rows:
            stmt = pg_insert(ProductOptionValue.__table__).values(pov_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["product_option_value_uuid"])
            db.execute(stmt)

        if pbp_rows:
            stmt = pg_insert(ProductBasePrice.__table__).values(pbp_rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["product_baseprice_uuid"])
            db.execute(stmt)

        db.commit()

        return {
            "ok": True,
            "synced_products": len(product_rows),
            "option_groups": len(pog_rows),
            "option_values": len(pov_rows),
            "baseprices": len(pbp_rows),
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# Tester endpoints (DB-backed)
# ---------------------------

@app.get("/doorhangers/tester")
def doorhangers_tester(product_uuid: Optional[str] = None, db: Session = Depends(get_db)):
    """
    If no product_uuid: returns product list.
    If product_uuid: returns option groups + values + baseprices for dropdown testing.
    """
    if not product_uuid:
        items = db.query(Product).order_by(Product.product_code.asc().nulls_last()).limit(200).all()
        return {
            "count": len(items),
            "products": [
                {
                    "product_uuid": p.product_uuid,
                    "product_code": p.product_code,
                    "product_description": p.product_description,
                }
                for p in items
            ],
        }

    p = db.get(Product, product_uuid)
    if not p:
        raise HTTPException(status_code=404, detail="product_uuid not found in DB. Run /sync/doorhangers first.")

    groups = (
        db.query(ProductOptionGroup)
        .filter(ProductOptionGroup.product_uuid == product_uuid)
        .order_by(ProductOptionGroup.name.asc().nulls_last())
        .all()
    )

    out_groups = []
    for g in groups:
        vals = (
            db.query(ProductOptionValue)
            .filter(ProductOptionValue.product_option_group_uuid == g.product_option_group_uuid)
            .order_by(ProductOptionValue.sort.asc().nulls_last(), ProductOptionValue.name.asc().nulls_last())
            .all()
        )
        out_groups.append(
            {
                "product_option_group_uuid": g.product_option_group_uuid,
                "name": g.name,
                "minoccurs": g.minoccurs,
                "maxoccurs": g.maxoccurs,
                "values": [
                    {
                        "product_option_value_uuid": v.product_option_value_uuid,
                        "name": v.name,
                        "code": v.code,
                        "sort": v.sort,
                    }
                    for v in vals
                ],
            }
        )

    prices = (
        db.query(ProductBasePrice)
        .filter(ProductBasePrice.product_uuid == product_uuid)
        .order_by(ProductBasePrice.quantity.asc().nulls_last())
        .all()
    )

    return {
        "product": {
            "product_uuid": p.product_uuid,
            "product_code": p.product_code,
            "product_description": p.product_description,
        },
        "option_groups": out_groups,
        "baseprices": [
            {
                "product_baseprice_uuid": bp.product_baseprice_uuid,
                "quantity": bp.quantity,
                "turnaround": bp.turnaround,
                "price": float(bp.price) if bp.price is not None else None,
            }
            for bp in prices
        ],
        "next_step": {
            "note": "To price a specific selection, use /doorhangers/quote (runtime pricing) once you know runsize/colorspec/turnaround UUIDs.",
        },
    }


@app.get("/doorhangers/help")
def doorhangers_help():
    base = "https://web-production-009a.up.railway.app"
    return {
        "tests": {
            "whoami": f"{base}/4over/whoami",
            "db_ping": f"{base}/db/ping",
            "reset_schema": f"{base}/db/reset_tester_schema",
            "sync_25": f"{base}/sync/doorhangers?max=25&offset=0",
            "tester_list": f"{base}/doorhangers/tester",
            "tester_one": f"{base}/doorhangers/tester?product_uuid=<PRODUCT_UUID>",
            "quote_template": f"{base}/doorhangers/quote?product_uuid=<PRODUCT_UUID>&colorspec_uuid=<COLOR_UUID>&runsize_uuid=<RUN_UUID>&turnaroundtime_uuid=<TAT_UUID>&option_uuids=<OPT1>&option_uuids=<OPT2>",
        },
        "doorhangers_category_uuid": DOORHANGERS_CATEGORY_UUID,
        "note": "If tester_one errors, POST reset_schema, then POST sync_25 again.",
    }
