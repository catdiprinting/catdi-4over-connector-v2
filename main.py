from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
import os
import traceback

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from db import engine, Base, get_db, db_ping
from fourover_client import FourOverClient

from models_pricing import (
    PricingProduct,
    PricingOptionGroup,
    PricingOption,
    PricingBasePrice,
)
from pricing_tester import router as pricing_router

APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PRICING_TESTER"
BUILD = "SAFE_AND_STABLE_2025-12-30_FIX_DEPENDS"

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0") == "1"

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"
BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://web-production-009a.up.railway.app")

app = FastAPI(title=APP_NAME)

# Create pricing tables
Base.metadata.create_all(bind=engine)

# Include pricing router
app.include_router(pricing_router)

_client = None


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


def _entities(payload):
    if isinstance(payload, dict) and "entities" in payload and isinstance(payload["entities"], list):
        return payload["entities"]
    if isinstance(payload, list):
        return payload
    return []


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/db/ping")
def db_ping_route():
    db_ping()
    return {"ok": True}


@app.get("/4over/whoami")
def whoami():
    r, _dbg = four_over().get("/whoami", params={})
    if not r.ok:
        return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
    return r.json()


@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    path = f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products"
    r, dbg = four_over().get(path, params={"max": max, "offset": offset})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()


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


@app.get("/doorhangers/bundle/{product_uuid}")
def doorhangers_bundle(product_uuid: str):
    # Find product details from category list (simple + reliable)
    prod_payload = doorhangers_products(max=5000, offset=0)
    items = _entities(prod_payload)

    product = None
    for p in items:
        if str(p.get("product_uuid")) == str(product_uuid):
            product = {
                "product_uuid": str(p.get("product_uuid")),
                "product_code": p.get("product_code"),
                "product_description": p.get("product_description"),
            }
            break

    if not product:
        raise HTTPException(status_code=404, detail="product_uuid not found in /doorhangers/products")

    og = doorhangers_optiongroups(product_uuid)
    bp = doorhangers_baseprices(product_uuid)

    return {"product": product, "optiongroups": og, "baseprices": bp}


@app.post("/doorhangers/import/{product_uuid}")
def doorhangers_import(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull bundle from 4over and import into Postgres pricing tables.
    """
    bundle = doorhangers_bundle(product_uuid)

    product = bundle["product"]
    optiongroups = bundle["optiongroups"]
    baseprices = bundle["baseprices"]

    # Upsert product
    existing = db.get(PricingProduct, product_uuid)
    if not existing:
        existing = PricingProduct(
            product_uuid=product_uuid,
            product_code=product.get("product_code"),
            product_description=product.get("product_description"),
        )
        db.add(existing)
    else:
        existing.product_code = product.get("product_code")
        existing.product_description = product.get("product_description")

    # Delete old per-product safely
    group_rows = db.execute(
        sql_text(
            "SELECT product_option_group_uuid FROM pricing_option_groups WHERE product_uuid = :p"
        ),
        {"p": product_uuid},
    ).fetchall()
    group_uuids = [r[0] for r in group_rows]

    if group_uuids:
        db.execute(
            sql_text("DELETE FROM pricing_options WHERE group_uuid = ANY(:ids)"),
            {"ids": group_uuids},
        )

    db.execute(sql_text("DELETE FROM pricing_option_groups WHERE product_uuid = :p"), {"p": product_uuid})
    db.execute(sql_text("DELETE FROM pricing_base_prices WHERE product_uuid = :p"), {"p": product_uuid})

    # Insert option groups + options
    for g in optiongroups.get("entities", []):
        guid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
        if not guid:
            continue

        grp = PricingOptionGroup(
            product_option_group_uuid=str(guid),
            product_uuid=product_uuid,
            name=g.get("name"),
            minoccurs=int(g.get("minoccurs")) if str(g.get("minoccurs", "")).isdigit() else None,
            maxoccurs=int(g.get("maxoccurs")) if str(g.get("maxoccurs", "")).isdigit() else None,
        )
        db.add(grp)

        values = g.get("values") or g.get("options") or []
        for v in values:
            vuid = v.get("product_option_value_uuid") or v.get("option_uuid") or v.get("uuid")
            if not vuid:
                continue

            db.add(
                PricingOption(
                    option_uuid=str(vuid),
                    group_uuid=str(guid),
                    option_name=v.get("name"),
                    option_description=v.get("description"),
                    capi_name=v.get("capi_name"),
                    capi_description=v.get("capi_description"),
                    runsize_uuid=v.get("runsize_uuid"),
                    runsize=v.get("runsize"),
                    colorspec_uuid=v.get("colorspec_uuid"),
                    colorspec=v.get("colorspec"),
                )
            )

    # Insert base prices (IMPORTANT: uses base_price_uuid + product_baseprice)
    for b in baseprices.get("entities", []):
        buid = b.get("base_price_uuid") or b.get("product_baseprice_uuid") or b.get("uuid")
        if not buid:
            continue

        db.add(
            PricingBasePrice(
                base_price_uuid=str(buid),
                product_uuid=product_uuid,
                product_baseprice=str(b.get("product_baseprice") or b.get("price") or "0"),
                runsize_uuid=b.get("runsize_uuid"),
                runsize=str(b.get("runsize")) if b.get("runsize") is not None else None,
                colorspec_uuid=b.get("colorspec_uuid"),
                colorspec=str(b.get("colorspec")) if b.get("colorspec") is not None else None,
                can_group_ship=bool(b.get("can_group_ship", False)),
            )
        )

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "tester_ui": f"{BASE_URL}/pricing/tester/{product_uuid}",
    }


@app.get("/doorhangers/matrix_keys")
def doorhangers_matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    UI helper: return distinct runsizes/colorspecs for dropdowns.
    """
    runs = db.execute(
        sql_text(
            """
            SELECT DISTINCT runsize_uuid, runsize
            FROM pricing_base_prices
            WHERE product_uuid = :p AND runsize_uuid IS NOT NULL
            ORDER BY runsize::int NULLS LAST, runsize
            """
        ),
        {"p": product_uuid},
    ).fetchall()

    cols = db.execute(
        sql_text(
            """
            SELECT DISTINCT colorspec_uuid, colorspec
            FROM pricing_base_prices
            WHERE product_uuid = :p AND colorspec_uuid IS NOT NULL
            ORDER BY colorspec
            """
        ),
        {"p": product_uuid},
    ).fetchall()

    return {
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": r[0], "runsize": r[1]} for r in runs],
        "colorspecs": [{"colorspec_uuid": c[0], "colorspec": c[1]} for c in cols],
    }


@app.get("/help")
def help_routes():
    return {
        "tests": {
            "health": f"{BASE_URL}/health",
            "db_ping": f"{BASE_URL}/db/ping",
            "whoami": f"{BASE_URL}/4over/whoami",
            "doorhangers_products": f"{BASE_URL}/doorhangers/products?max=25&offset=0",
            "bundle": f"{BASE_URL}/doorhangers/bundle/<PRODUCT_UUID>",
            "import": f"{BASE_URL}/doorhangers/import/<PRODUCT_UUID>",
            "pricing_products": f"{BASE_URL}/pricing/products",
            "pricing_tester_ui": f"{BASE_URL}/pricing/tester/<PRODUCT_UUID>",
        },
        "note": "Run import first, then open pricing tester UI.",
    }
