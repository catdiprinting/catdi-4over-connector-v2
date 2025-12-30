# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional
import re
import json
from decimal import Decimal

from fourover_client import FourOverClient

from db import engine, db_ping, SessionLocal
import models  # IMPORTANT: registers SQLAlchemy models


APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE1"
BUILD = "BASELINE_WHOAMI_WORKING_2025-12-29_DB_SYNC_TESTER_V1"

# Door Hangers category UUID you provided
DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

app = FastAPI(title=APP_NAME)

_client: Optional[FourOverClient] = None


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
    """
    Pull sizes like: 3.5" X 8.5" or 4.25" X 11" from product_description
    """
    if not desc:
        return None
    m = re.search(r'(\d+(\.\d+)?)"\s*X\s*(\d+(\.\d+)?)"', desc)
    if not m:
        return None
    return f'{m.group(1)}" x {m.group(3)}"'


def _extract_stock_from_desc(desc: str) -> Optional[str]:
    """
    Lightweight parsing based on examples.
    Optiongroups are source of truth; this is just a hint.
    """
    if not desc:
        return None
    if "14PT" in desc:
        return "14PT"
    if "16PT" in desc:
        return "16PT"
    if "100LB" in desc and "BOOK" in desc:
        return "100LB Gloss Book"
    if "100LB" in desc and "Cover" in desc:
        return "100LB Gloss Cover"
    return None


@app.on_event("startup")
def _startup():
    # Create tables safely (no-op if already exist)
    models.Base.metadata.create_all(bind=engine)

    # Optional quick ping (helps you confirm Railway Postgres is up)
    try:
        db_ping()
    except Exception as e:
        # Don't crash startup; just log-ish as response in /db/ping
        print(f"[WARN] DB ping failed on startup: {e}")


def _db():
    return SessionLocal()


# ---------------------------
# Core
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


@app.post("/db/ping")
def db_ping_route():
    try:
        db_ping()
        return {"ok": True, "db": "reachable"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {e}")


# ---------------------------
# 4over passthroughs (existing)
# ---------------------------

@app.get("/4over/whoami")
def whoami():
    try:
        r, _dbg = four_over().get("/whoami", params={})
        if not r.ok:
            return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/printproducts/categories")
def categories(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    try:
        r, dbg = four_over().get("/printproducts/categories", params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def category_products(
    category_uuid: str,
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    try:
        path = f"/printproducts/categories/{category_uuid}/products"
        r, dbg = four_over().get(path, params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# Door Hangers: Phase 1 (existing)
# ---------------------------

@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Pull the Door Hangers product list.
    """
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)


@app.get("/doorhangers/products/summary")
def doorhangers_products_summary(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Quick summarizer: derive Size + Stock + Coating hint from description/code.
    (Optiongroups will be source of truth later.)
    """
    data = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)

    if isinstance(data, dict) and "entities" in data:
        items = data["entities"]
    else:
        items = data if isinstance(data, list) else []

    out = []
    for p in items:
        desc = p.get("product_description", "") or ""
        code = p.get("product_code", "") or ""
        size = _extract_size_from_desc(desc)
        stock = _extract_stock_from_desc(desc)

        coating = None
        # from code fragments: DHAQ, DHUV, DHUC, DHUVFR, DHSA
        if "DHAQ" in code:
            coating = "AQ"
        elif "DHSA" in code:
            coating = "Satin AQ"
        elif "DHUVFR" in code:
            coating = "Full UV Front Only"
        elif "DHUV" in code:
            coating = "UV"
        elif "DHUC" in code:
            coating = "Uncoated"

        out.append(
            {
                "product_uuid": p.get("product_uuid"),
                "product_code": code,
                "size_hint": size,
                "stock_hint": stock,
                "coating_hint": coating,
                "product_description": desc,
                "optiongroups_path": p.get("product_option_groups"),
                "baseprices_path": p.get("product_base_prices"),
            }
        )

    return {"count": len(out), "items": out}


@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
    """
    Pull option groups for a single product (dropdown options live here).
    """
    try:
        path = f"/printproducts/products/{product_uuid}/optiongroups"
        r, dbg = four_over().get(path, params={"max": 1000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    """
    Pull base prices for a single product (quantity/colorspec pricing lives here).
    """
    try:
        path = f"/printproducts/products/{product_uuid}/baseprices"
        r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/doorhangers/help")
def doorhangers_help():
    """
    Handy list of hyperlinked tests for Door Hangers.
    """
    base = "https://web-production-009a.up.railway.app"
    return {
        "tests": {
            "whoami": f"{base}/4over/whoami",
            "doorhangers_products": f"{base}/doorhangers/products?max=1000&offset=0",
            "doorhangers_summary": f"{base}/doorhangers/products/summary?max=1000&offset=0",
            "pick_a_product_uuid_then_optiongroups": f"{base}/doorhangers/product/<PRODUCT_UUID>/optiongroups",
            "pick_a_product_uuid_then_baseprices": f"{base}/doorhangers/product/<PRODUCT_UUID>/baseprices",
            "db_ping": f"{base}/db/ping",
            "sync_all": f"{base}/doorhangers/sync_all?pages=1&max=1000",
            "tester": f"{base}/pricing/doorhangers/tester",
        },
        "doorhangers_category_uuid": DOORHANGERS_CATEGORY_UUID,
        "note": "Sync to DB first, then pricing tester reads from DB.",
    }


# ---------------------------
# DB Sync (NEW)
# ---------------------------

def _upsert_products(db, products: List[Dict[str, Any]], category_uuid: str):
    for p in products:
        puid = p.get("product_uuid")
        if not puid:
            continue

        existing = db.get(models.Product, puid)
        raw = json.dumps(p, ensure_ascii=False)

        if existing:
            existing.product_code = p.get("product_code")
            existing.product_description = p.get("product_description")
            existing.category_uuid = category_uuid
            existing.raw_json = raw
        else:
            db.add(
                models.Product(
                    product_uuid=puid,
                    product_code=p.get("product_code"),
                    product_description=p.get("product_description"),
                    category_uuid=category_uuid,
                    raw_json=raw,
                )
            )


def _replace_optiongroups_and_options(db, product_uuid: str, optiongroups_payload: Dict[str, Any]):
    # Wipe existing for product (simple + safe for phase 1)
    db.query(models.Option).filter(
        models.Option.product_option_group_uuid.in_(
            db.query(models.OptionGroup.product_option_group_uuid).filter(
                models.OptionGroup.product_uuid == product_uuid
            )
        )
    ).delete(synchronize_session=False)

    db.query(models.OptionGroup).filter(models.OptionGroup.product_uuid == product_uuid).delete(
        synchronize_session=False
    )

    entities = optiongroups_payload.get("entities") or []
    for g in entities:
        group_uuid = g.get("product_option_group_uuid")
        if not group_uuid:
            continue

        def _to_int(x):
            try:
                return int(x)
            except Exception:
                return None

        og = models.OptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            product_option_group_name=g.get("product_option_group_name") or "",
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(og)

        for opt in (g.get("options") or []):
            ouuid = opt.get("option_uuid")
            if not ouuid:
                continue
            db.add(
                models.Option(
                    option_uuid=ouuid,
                    product_option_group_uuid=group_uuid,
                    option_name=opt.get("option_name"),
                    option_description=opt.get("option_description"),
                    runsize_uuid=opt.get("runsize_uuid"),
                    runsize=opt.get("runsize"),
                    colorspec_uuid=opt.get("colorspec_uuid"),
                    colorspec=opt.get("colorspec") or opt.get("capi_name"),
                    option_prices_url=opt.get("option_prices"),
                )
            )


def _replace_baseprices(db, product_uuid: str, baseprices_payload: Dict[str, Any]):
    # Wipe existing baseprices for product
    db.query(models.BasePrice).filter(models.BasePrice.product_uuid == product_uuid).delete(
        synchronize_session=False
    )

    entities = baseprices_payload.get("entities") or []
    for bp in entities:
        bpuuid = bp.get("base_price_uuid")
        if not bpuuid:
            continue

        # Prices come as strings; store as Decimal
        try:
            price = Decimal(str(bp.get("product_baseprice")))
        except Exception:
            continue

        db.add(
            models.BasePrice(
                base_price_uuid=bpuuid,
                product_uuid=product_uuid,
                product_baseprice=price,
                runsize_uuid=bp.get("runsize_uuid"),
                runsize=str(bp.get("runsize") or ""),
                colorspec_uuid=bp.get("colorspec_uuid"),
                colorspec=str(bp.get("colorspec") or ""),
                can_group_ship=bool(bp.get("can_group_ship")),
            )
        )


@app.post("/doorhangers/sync/products")
def sync_doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Sync ONLY the products list for Door Hangers into DB.
    """
    data = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)
    if not isinstance(data, dict) or "entities" not in data:
        return {"ok": False, "error": "Unexpected response from 4over", "data": data}

    db = _db()
    try:
        _upsert_products(db, data["entities"], DOORHANGERS_CATEGORY_UUID)
        db.commit()
        return {"ok": True, "synced_products": len(data["entities"]), "offset": offset, "max": max}
    finally:
        db.close()


@app.post("/doorhangers/sync/{product_uuid}")
def sync_doorhangers_product(product_uuid: str):
    """
    Sync optiongroups + baseprices for a single product_uuid into DB.
    """
    db = _db()
    try:
        # Ensure product exists (or create minimal stub)
        p = db.get(models.Product, product_uuid)
        if not p:
            db.add(models.Product(product_uuid=product_uuid, category_uuid=DOORHANGERS_CATEGORY_UUID))
            db.commit()

        og = doorhangers_optiongroups(product_uuid)
        if isinstance(og, dict) and og.get("ok") is False:
            return og

        bp = doorhangers_baseprices(product_uuid)
        if isinstance(bp, dict) and bp.get("ok") is False:
            return bp

        _replace_optiongroups_and_options(db, product_uuid, og)
        _replace_baseprices(db, product_uuid, bp)

        db.commit()
        return {
            "ok": True,
            "product_uuid": product_uuid,
            "optiongroups_count": len((og.get("entities") or [])),
            "baseprices_count": len((bp.get("entities") or [])),
        }
    finally:
        db.close()


@app.post("/doorhangers/sync_all")
def sync_doorhangers_all(
    pages: int = Query(1, ge=1, le=50),
    max: int = Query(1000, ge=1, le=5000),
):
    """
    Sync:
      1) Doorhangers products list (paged)
      2) For each product_uuid: optiongroups + baseprices

    This is the key to avoid "choking" in commerce: once synced, the calculator uses DB reads.
    """
    db = _db()
    try:
        synced_products = 0
        synced_details = 0

        for page in range(pages):
            offset = page * max
            data = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)

            if not isinstance(data, dict) or "entities" not in data:
                return {"ok": False, "error": "Unexpected response from 4over", "data": data, "page": page}

            items = data["entities"] or []
            if not items:
                break

            _upsert_products(db, items, DOORHANGERS_CATEGORY_UUID)
            db.commit()
            synced_products += len(items)

            # Sync optiongroups/baseprices per product
            for p in items:
                puid = p.get("product_uuid")
                if not puid:
                    continue

                og = doorhangers_optiongroups(puid)
                if isinstance(og, dict) and og.get("ok") is False:
                    continue

                bp = doorhangers_baseprices(puid)
                if isinstance(bp, dict) and bp.get("ok") is False:
                    continue

                _replace_optiongroups_and_options(db, puid, og)
                _replace_baseprices(db, puid, bp)
                db.commit()
                synced_details += 1

        return {"ok": True, "synced_products": synced_products, "synced_product_details": synced_details}
    finally:
        db.close()


# ---------------------------
# Pricing Tester (NEW)
# ---------------------------

def _group_options(db, product_uuid: str) -> List[Dict[str, Any]]:
    """
    Return option groups + options in a structured way for a front-end calculator.
    """
    groups = (
        db.query(models.OptionGroup)
        .filter(models.OptionGroup.product_uuid == product_uuid)
        .order_by(models.OptionGroup.product_option_group_name.asc())
        .all()
    )

    out = []
    for g in groups:
        opts = (
            db.query(models.Option)
            .filter(models.Option.product_option_group_uuid == g.product_option_group_uuid)
            .order_by(models.Option.option_name.asc().nulls_last())
            .all()
        )

        out.append(
            {
                "group_uuid": g.product_option_group_uuid,
                "group_name": g.product_option_group_name,
                "minoccurs": g.minoccurs,
                "maxoccurs": g.maxoccurs,
                "options": [
                    {
                        "option_uuid": o.option_uuid,
                        "option_name": o.option_name,
                        "option_description": o.option_description,
                        "runsize_uuid": o.runsize_uuid,
                        "runsize": o.runsize,
                        "colorspec_uuid": o.colorspec_uuid,
                        "colorspec": o.colorspec,
                        "option_prices_url": o.option_prices_url,
                    }
                    for o in opts
                ],
            }
        )
    return out


@app.get("/pricing/doorhangers/tester")
def pricing_tester_doorhangers(
    product_uuid: Optional[str] = Query(None, description="If omitted, we pick the first Door Hangers product in DB."),
    runsize_uuid: Optional[str] = Query(None),
    colorspec_uuid: Optional[str] = Query(None),
):
    """
    Returns:
      - available products (doorhangers)
      - optiongroups/options for selected product
      - base price if runsize_uuid + colorspec_uuid provided

    This is the foundation for a VistaPrint-like calculator:
      Front-end renders these groups as dropdowns and hits this endpoint to resolve price.
    """
    db = _db()
    try:
        # pick default product if none provided
        if not product_uuid:
            p0 = (
                db.query(models.Product)
                .filter(models.Product.category_uuid == DOORHANGERS_CATEGORY_UUID)
                .order_by(models.Product.product_code.asc().nulls_last())
                .first()
            )
            if not p0:
                return {
                    "ok": False,
                    "error": "No doorhangers products in DB yet. Run POST /doorhangers/sync_all first.",
                }
            product_uuid = p0.product_uuid

        product = db.get(models.Product, product_uuid)
        if not product:
            return {"ok": False, "error": f"Product not found in DB: {product_uuid}"}

        # product picker list (so UI can switch between SKUs)
        products = (
            db.query(models.Product)
            .filter(models.Product.category_uuid == DOORHANGERS_CATEGORY_UUID)
            .order_by(models.Product.product_code.asc().nulls_last())
            .all()
        )

        optiongroups = _group_options(db, product_uuid)

        # Gather distinct runsize/colorspec from base prices (this is your core pricing matrix)
        base_rows = (
            db.query(models.BasePrice)
            .filter(models.BasePrice.product_uuid == product_uuid)
            .order_by(models.BasePrice.runsize.asc().nulls_last(), models.BasePrice.colorspec.asc().nulls_last())
            .all()
        )

        runsizes = {}
        colorspecs = {}
        for r in base_rows:
            runsizes[r.runsize_uuid] = r.runsize
            colorspecs[r.colorspec_uuid] = r.colorspec

        price = None
        matched = None
        if runsize_uuid and colorspec_uuid:
            matched = (
                db.query(models.BasePrice)
                .filter(
                    models.BasePrice.product_uuid == product_uuid,
                    models.BasePrice.runsize_uuid == runsize_uuid,
                    models.BasePrice.colorspec_uuid == colorspec_uuid,
                )
                .first()
            )
            if matched:
                price = str(matched.product_baseprice)

        return {
            "ok": True,
            "selected": {
                "product_uuid": product.product_uuid,
                "product_code": product.product_code,
                "product_description": product.product_description,
            },
            "products": [
                {
                    "product_uuid": p.product_uuid,
                    "product_code": p.product_code,
                    "product_description": p.product_description,
                }
                for p in products
            ],
            "optiongroups": optiongroups,
            "pricing_matrix": {
                "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in runsizes.items()],
                "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspecs.items()],
            },
            "lookup": {
                "runsize_uuid": runsize_uuid,
                "colorspec_uuid": colorspec_uuid,
                "base_price": price,
            },
        }
    finally:
        db.close()
