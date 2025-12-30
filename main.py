from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse
import os
import traceback

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
BUILD = "SAFE_AND_STABLE_2025-12-30_FIX_IMPORT_500"

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "0") == "1"

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"
BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://web-production-009a.up.railway.app")

app = FastAPI(title=APP_NAME)

# Create DB tables (pricing tables + anything in Base)
Base.metadata.create_all(bind=engine)

# Include pricing router
app.include_router(pricing_router)

_client = None


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    # If you set DEBUG_ERRORS=1 in Railway, you’ll get the full trace.
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


# --------------------------
# 4over Doorhangers helpers
# --------------------------

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
    # Grab product details from category list (cheap + reliable)
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


# --------------------------
# Import: 4over -> Postgres
# --------------------------

@app.post("/doorhangers/import/{product_uuid}")
def doorhangers_import(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull bundle from 4over and import into Postgres pricing tables.
    Safe to re-run for the same product_uuid.
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

    # --- IMPORTANT FIX ---
    # Do NOT use raw SQL ANY(:ids) (often causes 500).
    # Do clean per-product deletes using ORM + fetched UUID list.
    group_uuids = [
        g[0]
        for g in db.query(PricingOptionGroup.product_option_group_uuid)
        .filter(PricingOptionGroup.product_uuid == product_uuid)
        .all()
    ]

    if group_uuids:
        db.query(PricingOption).filter(PricingOption.group_uuid.in_(group_uuids)).delete(synchronize_session=False)

    db.query(PricingOptionGroup).filter(PricingOptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(PricingBasePrice).filter(PricingBasePrice.product_uuid == product_uuid).delete(synchronize_session=False)

    # Insert option groups + options
    og_entities = optiongroups.get("entities", []) if isinstance(optiongroups, dict) else []
    for g in og_entities:
        guid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
        if not guid:
            continue

        db.add(
            PricingOptionGroup(
                product_option_group_uuid=str(guid),
                product_uuid=product_uuid,
                name=g.get("name"),
                minoccurs=_to_int(g.get("minoccurs")),
                maxoccurs=_to_int(g.get("maxoccurs")),
            )
        )

        values = g.get("values") or g.get("options") or []
        if isinstance(values, list):
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

    # Insert base prices (matrix)
    bp_entities = baseprices.get("entities", []) if isinstance(baseprices, dict) else []
    for b in bp_entities:
        buid = b.get("base_price_uuid") or b.get("product_baseprice_uuid") or b.get("uuid")
        if not buid:
            continue

        db.add(
            PricingBasePrice(
                base_price_uuid=str(buid),
                product_uuid=product_uuid,
                product_baseprice=_to_decimal(b.get("product_baseprice") or b.get("price")),
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
        "imported_groups": len(og_entities),
        "imported_prices": len(bp_entities),
        "tester_ui": f"{BASE_URL}/pricing/tester/{product_uuid}",
        "matrix_keys": f"{BASE_URL}/doorhangers/matrix_keys?product_uuid={product_uuid}",
    }


@app.get("/doorhangers/matrix_keys")
def doorhangers_matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    Return distinct runsizes/colorspecs from DB (for dropdowns).
    No integer casting (casting can 500 if a value isn't numeric).
    """
    runs = (
        db.query(PricingBasePrice.runsize_uuid, PricingBasePrice.runsize)
        .filter(PricingBasePrice.product_uuid == product_uuid)
        .filter(PricingBasePrice.runsize_uuid.isnot(None))
        .distinct()
        .order_by(PricingBasePrice.runsize.asc().nulls_last())
        .all()
    )

    cols = (
        db.query(PricingBasePrice.colorspec_uuid, PricingBasePrice.colorspec)
        .filter(PricingBasePrice.product_uuid == product_uuid)
        .filter(PricingBasePrice.colorspec_uuid.isnot(None))
        .distinct()
        .order_by(PricingBasePrice.colorspec.asc().nulls_last())
        .all()
    )

    return {
        "ok": True,
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
            "doorhangers_products": f"{BASE_URL}/doorhangers/products?max=5&offset=0",
            "bundle": f"{BASE_URL}/doorhangers/bundle/{'<PRODUCT_UUID>'}",
            "import": f"{BASE_URL}/doorhangers/import/{'<PRODUCT_UUID>'}",
            "matrix_keys": f"{BASE_URL}/doorhangers/matrix_keys?product_uuid={'<PRODUCT_UUID>'}",
            "pricing_products": f"{BASE_URL}/pricing/products",
            "pricing_config": f"{BASE_URL}/pricing/product/{'<PRODUCT_UUID>'}/config",
            "pricing_price": f"{BASE_URL}/pricing/price?product_uuid={'<PRODUCT_UUID>'}&runsize_uuid={'<RUNSIZE_UUID>'}&colorspec_uuid={'<COLORSPEC_UUID>'}",
            "pricing_tester_ui": f"{BASE_URL}/pricing/tester/{'<PRODUCT_UUID>'}",
        },
        "note": "Run POST /doorhangers/import/<PRODUCT_UUID> first. Then /doorhangers/matrix_keys and open /pricing/tester/<PRODUCT_UUID>.",
    }


def _to_int(v):
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_decimal(v):
    if v is None:
        return "0"
    return str(v)
