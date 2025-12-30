from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from typing import Any, Dict, Optional
import re
from sqlalchemy import text
from sqlalchemy.orm import Session

from fourover_client import FourOverClient  # IMPORTANT: keep YOUR working version
from db import get_db, db_ping, engine
from models import Product, ProductOptionGroup, ProductOptionValue, ProductBasePrice
from db import Base

APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE1"
BUILD = "PRICING_TESTER_DB_SYNC_TRUNCATE_2025-12-30"

# Door Hangers category UUID
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
    if not desc:
        return None
    m = re.search(r'(\d+(\.\d+)?)"\s*X\s*(\d+(\.\d+)?)"', desc)
    if not m:
        return None
    return f'{m.group(1)}" x {m.group(3)}"'


@app.on_event("startup")
def startup():
    # Ensure tables exist (for tester mode)
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


# ✅ FIX for your "Method Not Allowed": make db ping a GET route
@app.get("/db/ping")
def db_ping_route():
    try:
        db_ping()
        return {"ok": True, "db": "reachable"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
def category_products(category_uuid: str, max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    try:
        path = f"/printproducts/categories/{category_uuid}/products"
        r, dbg = four_over().get(path, params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# Door Hangers: API passthrough
# ---------------------------

@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)


@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
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
    try:
        path = f"/printproducts/products/{product_uuid}/baseprices"
        r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# ✅ SYNC: Door Hangers -> DB (Tester Mode)
# No joins, no ORM query.delete/update. Uses TRUNCATE.
# ---------------------------

def _truncate_tester_tables(db: Session):
    # CASCADE handles FK relationships safely.
    db.execute(text("TRUNCATE TABLE product_baseprices RESTART IDENTITY CASCADE"))
    db.execute(text("TRUNCATE TABLE product_option_values RESTART IDENTITY CASCADE"))
    db.execute(text("TRUNCATE TABLE product_option_groups RESTART IDENTITY CASCADE"))
    db.execute(text("TRUNCATE TABLE products RESTART IDENTITY CASCADE"))


@app.post("/sync/doorhangers")
def sync_doorhangers(
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Pull Door Hangers product list + optiongroups + baseprices for each product,
    store in Postgres for pricing tester UI.
    """
    try:
        # 1) Fetch products list
        data = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)
        entities = data.get("entities", [])
        if not isinstance(entities, list):
            raise HTTPException(status_code=500, detail="Unexpected 4over products response (entities missing)")

        # 2) wipe tester tables (safe)
        _truncate_tester_tables(db)

        # 3) Insert products
        for p in entities:
            db.add(
                Product(
                    product_uuid=p.get("product_uuid"),
                    product_code=p.get("product_code"),
                    product_description=p.get("product_description"),
                    full_product_path=p.get("full_product_path"),
                    categories_path=p.get("categories"),
                    optiongroups_path=p.get("product_option_groups"),
                    baseprices_path=p.get("product_base_prices"),
                )
            )
        db.flush()

        # 4) For each product: fetch optiongroups + baseprices and store
        for p in entities:
            product_uuid = p.get("product_uuid")
            if not product_uuid:
                continue

            og = doorhangers_optiongroups(product_uuid)
            og_entities = og.get("entities", []) if isinstance(og, dict) else []

            for group in og_entities:
                group_uuid = group.get("product_option_group_uuid")
                db.add(
                    ProductOptionGroup(
                        product_option_group_uuid=group_uuid,
                        product_uuid=product_uuid,
                        name=group.get("product_option_group_name"),
                        minoccurs=str(group.get("minoccurs")) if group.get("minoccurs") is not None else None,
                        maxoccurs=str(group.get("maxoccurs")) if group.get("maxoccurs") is not None else None,
                    )
                )

                options = group.get("options", []) or []
                for opt in options:
                    db.add(
                        ProductOptionValue(
                            option_uuid=opt.get("option_uuid"),
                            product_uuid=product_uuid,
                            product_option_group_uuid=group_uuid,
                            option_name=opt.get("option_name"),
                            option_description=opt.get("option_description"),
                            option_prices=opt.get("option_prices"),
                            runsize_uuid=opt.get("runsize_uuid"),
                            runsize=opt.get("runsize"),
                            colorspec_uuid=opt.get("colorspec_uuid"),
                            colorspec=opt.get("colorspec"),
                        )
                    )

            bp = doorhangers_baseprices(product_uuid)
            bp_entities = bp.get("entities", []) if isinstance(bp, dict) else []

            for row in bp_entities:
                db.add(
                    ProductBasePrice(
                        base_price_uuid=row.get("base_price_uuid"),
                        product_uuid=product_uuid,
                        product_baseprice=row.get("product_baseprice"),
                        runsize_uuid=row.get("runsize_uuid"),
                        runsize=row.get("runsize"),
                        colorspec_uuid=row.get("colorspec_uuid"),
                        colorspec=row.get("colorspec"),
                        can_group_ship=row.get("can_group_ship"),
                    )
                )

        db.commit()

        return {
            "ok": True,
            "synced_products": len(entities),
            "note": "Tester sync complete. Use /doorhangers/tester to browse options + prices from DB.",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# ✅ Pricing Tester Endpoint (DB-backed)
# ---------------------------

@app.get("/doorhangers/tester")
def doorhangers_tester(
    product_uuid: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    If product_uuid is not provided: returns a list of products (uuid, code, desc, size_hint)
    If product_uuid is provided: returns option groups + options + baseprices from DB
    """
    if not product_uuid:
        prods = db.query(Product).order_by(Product.product_code.asc().nulls_last()).all()
        out = []
        for p in prods:
            out.append(
                {
                    "product_uuid": p.product_uuid,
                    "product_code": p.product_code,
                    "product_description": p.product_description,
                    "size_hint": _extract_size_from_desc(p.product_description or ""),
                }
            )
        return {"count": len(out), "products": out}

    p = db.query(Product).filter(Product.product_uuid == product_uuid).first()
    if not p:
        raise HTTPException(status_code=404, detail="product_uuid not found in DB. Run /sync/doorhangers first.")

    groups = db.query(ProductOptionGroup).filter(ProductOptionGroup.product_uuid == product_uuid).all()
    options = db.query(ProductOptionValue).filter(ProductOptionValue.product_uuid == product_uuid).all()
    prices = db.query(ProductBasePrice).filter(ProductBasePrice.product_uuid == product_uuid).all()

    # build group->options map
    group_map: Dict[str, Any] = {}
    for g in groups:
        group_map[g.product_option_group_uuid] = {
            "group_uuid": g.product_option_group_uuid,
            "name": g.name,
            "minoccurs": g.minoccurs,
            "maxoccurs": g.maxoccurs,
            "options": [],
        }

    for o in options:
        g = group_map.get(o.product_option_group_uuid)
        if not g:
            # if a row has no group uuid, ignore in tester
            continue
        g["options"].append(
            {
                "option_uuid": o.option_uuid,
                "option_name": o.option_name,
                "option_description": o.option_description,
                "runsize": o.runsize,
                "colorspec": o.colorspec,
                "option_prices": o.option_prices,
            }
        )

    return {
        "product": {
            "product_uuid": p.product_uuid,
            "product_code": p.product_code,
            "product_description": p.product_description,
        },
        "option_groups": list(group_map.values()),
        "baseprices": [
            {
                "base_price_uuid": r.base_price_uuid,
                "runsize": r.runsize,
                "colorspec": r.colorspec,
                "product_baseprice": str(r.product_baseprice) if r.product_baseprice is not None else None,
            }
            for r in prices
        ],
    }


@app.get("/doorhangers/help")
def doorhangers_help():
    base = "https://web-production-009a.up.railway.app"
    return {
        "tests": {
            "whoami": f"{base}/4over/whoami",
            "db_ping": f"{base}/db/ping",
            "sync_doorhangers": f"curl -i -X POST \"{base}/sync/doorhangers?max=1000&offset=0\"",
            "tester_list_products": f"{base}/doorhangers/tester",
            "tester_single_product": f"{base}/doorhangers/tester?product_uuid=<PRODUCT_UUID>",
        },
        "doorhangers_category_uuid": DOORHANGERS_CATEGORY_UUID,
    }
