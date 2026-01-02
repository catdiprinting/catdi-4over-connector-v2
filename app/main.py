# app/main.py
import json
from decimal import Decimal
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from .db import get_db
from .models import Category, Product, ProductCategory, ProductDetail, BasePriceRow
from .fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector", version="v2-db-sync-fixed")
client = FourOverClient()


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/debug/auth")
def debug_auth():
    return {
        "FOUR_OVER_BASE_URL": client.base_url,
        "FOUR_OVER_API_PREFIX": client.api_prefix,
        "FOUR_OVER_APIKEY_present": bool(client.apikey),
        "FOUR_OVER_PRIVATE_KEY_present": bool(client.private_key),
        "FOUR_OVER_TIMEOUT": str(client.timeout),
    }


# --------------------------
# PASS-THROUGH (tests)
# --------------------------

@app.get("/4over/whoami")
def whoami():
    code, data = client.get("/whoami")
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories")
def categories(max: int = Query(50), offset: int = Query(0)):
    code, data = client.get("/categories", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(50), offset: int = Query(0)):
    code, data = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    code, data = client.get(f"/products/{product_uuid}")
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = Query(200), offset: int = Query(0)):
    code, data = client.get(f"/products/{product_uuid}/baseprices", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


# --------------------------
# SYNC: Categories → Products → Product Details → Base Prices
# --------------------------

@app.post("/sync/categories")
def sync_categories(db: Session = Depends(get_db), max: int = Query(50), offset: int = Query(0)):
    code, payload = client.get("/categories", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    entities = payload.get("entities", [])
    upserts = 0

    for c in entities:
        row = db.get(Category, c["category_uuid"])
        if not row:
            row = Category(category_uuid=c["category_uuid"])
            db.add(row)
        row.category_name = c.get("category_name") or ""
        row.category_description = c.get("category_description")
        upserts += 1

    db.commit()
    return {"ok": True, "upserts": upserts, "page": payload.get("currentPage"), "totalResults": payload.get("totalResults")}


@app.post("/sync/category/{category_uuid}/products")
def sync_category_products(category_uuid: str, db: Session = Depends(get_db), max: int = Query(50), offset: int = Query(0)):
    code, payload = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    entities = payload.get("entities", [])
    upserts = 0
    links = 0

    if not db.get(Category, category_uuid):
        db.add(Category(category_uuid=category_uuid, category_name="(unknown)", category_description=None))
        db.commit()

    for p in entities:
        puid = p["product_uuid"]
        prod = db.get(Product, puid)
        if not prod:
            prod = Product(product_uuid=puid)
            db.add(prod)
        prod.product_code = p.get("product_code")
        prod.product_description = p.get("product_description")
        upserts += 1

        existing = db.query(ProductCategory).filter_by(product_uuid=puid, category_uuid=category_uuid).first()
        if not existing:
            db.add(ProductCategory(product_uuid=puid, category_uuid=category_uuid))
            links += 1

    db.commit()
    return {"ok": True, "products_upserted": upserts, "links_added": links, "page": payload.get("currentPage"), "totalResults": payload.get("totalResults")}


@app.post("/sync/product/{product_uuid}")
def sync_product_detail(product_uuid: str, db: Session = Depends(get_db)):
    code, payload = client.get(f"/products/{product_uuid}")
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    prod = db.get(Product, product_uuid)
    if not prod:
        prod = Product(product_uuid=product_uuid)
        db.add(prod)

    prod.product_code = payload.get("product_code")
    prod.product_description = payload.get("product_description")

    details = db.get(ProductDetail, product_uuid)
    if not details:
        details = ProductDetail(product_uuid=product_uuid, raw_json=json.dumps(payload))
        db.add(details)
    else:
        details.raw_json = json.dumps(payload)

    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "stored": True}


@app.post("/sync/product/{product_uuid}/base-prices")
def sync_product_base_prices(product_uuid: str, db: Session = Depends(get_db)):
    max_page = 200
    offset = 0
    inserted = 0
    updated = 0

    while True:
        code, payload = client.get(f"/products/{product_uuid}/baseprices", params={"max": max_page, "offset": offset})
        if code >= 400:
            return {"ok": False, "http_code": code, "data": payload, "offset": offset}

        entities = payload.get("entities", []) or []
        if not entities:
            break

        for r in entities:
            base_price_uuid = r.get("base_price_uuid")
            if not base_price_uuid:
                continue

            existing = db.query(BasePriceRow).filter_by(product_uuid=product_uuid, base_price_uuid=base_price_uuid).first()
            if not existing:
                existing = BasePriceRow(product_uuid=product_uuid, base_price_uuid=base_price_uuid)
                db.add(existing)
                inserted += 1
            else:
                updated += 1

            existing.product_baseprice = Decimal(str(r.get("product_baseprice", "0")))
            existing.runsize_uuid = r.get("runsize_uuid")
            existing.runsize = r.get("runsize")
            existing.colorspec_uuid = r.get("colorspec_uuid")
            existing.colorspec = r.get("colorspec")
            existing.can_group_ship = r.get("can_group_ship")
            existing.raw_json = json.dumps(r)

        db.commit()

        offset += max_page

    return {"ok": True, "product_uuid": product_uuid, "inserted": inserted, "updated": updated}
