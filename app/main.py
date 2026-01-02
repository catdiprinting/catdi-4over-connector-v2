import json
from decimal import Decimal

from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from app.db import init_db, get_db
from app.models import Category, Product, ProductCategory, ProductDetail, BasePriceRow
from app.fourover_client import FourOverClient
from app.config import DEFAULT_MARKUP_PCT

app = FastAPI(title="catdi-4over-connector", version="v2-db-sync")

client = FourOverClient()


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector-v2", "phase": "db-sync"}


@app.post("/db/init")
def db_init():
    init_db()
    return {"ok": True, "message": "DB initialized (tables created if missing)"}


@app.get("/4over/whoami")
def whoami():
    code, data = client.get("/whoami")
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories")
def categories(max: int = Query(50), offset: int = Query(0)):
    code, data = client.get("/printproducts/categories", params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(50), offset: int = Query(0)):
    path = f"/printproducts/categories/{category_uuid}/products"
    code, data = client.get(path, params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    path = f"/printproducts/products/{product_uuid}"
    code, data = client.get(path)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


# Convenience endpoint: option groups as a standalone call
@app.get("/4over/products/{product_uuid}/option-groups")
def product_option_groups(product_uuid: str):
    """Returns raw option-groups for a single product."""
    path = f"/printproducts/products/{product_uuid}/optiongroups"
    code, data = client.get(path)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


# ✅ THIS is what your curl was missing:
@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = Query(200), offset: int = Query(0)):
    path = f"/printproducts/products/{product_uuid}/baseprices"
    code, data = client.get(path, params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


# --------------------------
# SYNC: Categories → Products → Product Details → Base Prices
# --------------------------

@app.post("/sync/categories")
def sync_categories(db: Session = Depends(get_db), max: int = Query(50), offset: int = Query(0)):
    code, payload = client.get("/printproducts/categories", params={"max": max, "offset": offset})
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
    path = f"/printproducts/categories/{category_uuid}/products"
    code, payload = client.get(path, params={"max": max, "offset": offset})
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    entities = payload.get("entities", [])
    upserts = 0
    links = 0

    # ensure category exists
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

        # link
        existing = db.query(ProductCategory).filter_by(product_uuid=puid, category_uuid=category_uuid).first()
        if not existing:
            db.add(ProductCategory(product_uuid=puid, category_uuid=category_uuid))
            links += 1

    db.commit()
    return {"ok": True, "products_upserted": upserts, "links_added": links, "page": payload.get("currentPage"), "totalResults": payload.get("totalResults")}


@app.post("/sync/product/{product_uuid}")
def sync_product_detail(product_uuid: str, db: Session = Depends(get_db)):
    code, payload = client.get(f"/printproducts/products/{product_uuid}")
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    # upsert product
    prod = db.get(Product, product_uuid)
    if not prod:
        prod = Product(product_uuid=product_uuid)
        db.add(prod)

    prod.product_code = payload.get("product_code")
    prod.product_description = payload.get("product_description")

    # upsert raw details
    details = db.get(ProductDetail, product_uuid)
    if not details:
        details = ProductDetail(product_uuid=product_uuid, raw_json=json.dumps(payload))
        db.add(details)
    else:
        details.raw_json = json.dumps(payload)

    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "stored": True}


# Alias (plural) because it's easy to type and older cURL examples used it
@app.post("/sync/products/{product_uuid}")
def sync_products_detail_alias(product_uuid: str, db: Session = Depends(get_db)):
    return sync_product_detail(product_uuid, db)


@app.post("/sync/product/{product_uuid}/base-prices")
def sync_product_base_prices(product_uuid: str, db: Session = Depends(get_db)):
    # Pull multiple pages safely
    max_page = 200
    offset = 0
    inserted = 0
    updated = 0

    while True:
        code, payload = client.get(f"/printproducts/products/{product_uuid}/baseprices", params={"max": max_page, "offset": offset})
        if code >= 400:
            return {"ok": False, "http_code": code, "data": payload, "offset": offset}

        entities = payload.get("entities", []) or []
        if not entities:
            break

        for r in entities:
            base_price_uuid = r.get("base_price_uuid") or r.get("base_price_uuid".replace("_", ""))  # defensive
            if not base_price_uuid:
                # sometimes payload uses base_price_uuid exactly, so this is just safety
                base_price_uuid = r.get("base_price_uuid")

            existing = db.query(BasePriceRow).filter_by(product_uuid=product_uuid, base_price_uuid=base_price_uuid).first()
            if not existing:
                existing = BasePriceRow(product_uuid=product_uuid, base_price_uuid=base_price_uuid)
                db.add(existing)
                inserted += 1
            else:
                updated += 1

            # map fields (based on your PDF docs snippet)
            existing.product_baseprice = Decimal(str(r.get("product_baseprice", "0")))
            existing.runsize_uuid = r.get("runsize_uuid")
            existing.runsize = r.get("runsize")
            existing.colorspec_uuid = r.get("colorspec_uuid")
            existing.colorspec = r.get("colorspec")
            existing.can_group_ship = r.get("can_group_ship")
            existing.raw_json = json.dumps(r)

        db.commit()

        # pagination
        total = payload.get("totalResults")
        offset += len(entities)
        if total is not None and offset >= int(total):
            break

    return {"ok": True, "product_uuid": product_uuid, "inserted": inserted, "updated": updated}


@app.post("/sync/doorhangers")
def sync_doorhangers(db: Session = Depends(get_db)):
    """
    Door Hangers category_uuid (from your curl output):
    5cacc269-e6a8-472d-91d6-792c4584cae8
    """
    category_uuid = "5cacc269-e6a8-472d-91d6-792c4584cae8"

    # 1) Sync first page of categories to ensure category table exists (optional)
    # 2) Sync all products in door hangers category
    max_page = 50
    offset = 0
    total_products_seen = 0
    product_uuids = []

    while True:
        code, payload = client.get(f"/printproducts/categories/{category_uuid}/products", params={"max": max_page, "offset": offset})
        if code >= 400:
            return {"ok": False, "http_code": code, "data": payload, "offset": offset}

        entities = payload.get("entities", []) or []
        if not entities:
            break

        # upsert page into DB + collect UUIDs
        for p in entities:
            puid = p["product_uuid"]
            product_uuids.append(puid)

        # write page rows into DB
        sync_category_products(category_uuid, db, max=max_page, offset=offset)

        total = payload.get("totalResults")
        offset += len(entities)
        total_products_seen += len(entities)

        if total is not None and offset >= int(total):
            break

    # For a “test but real” run: sync details + baseprices for first N products.
    # Change this to sync all once you're comfortable.
    N = 10
    synced = []
    for puid in product_uuids[:N]:
        sync_product_detail(puid, db)
        sync_product_base_prices(puid, db)
        synced.append(puid)

    return {"ok": True, "category_uuid": category_uuid, "products_found": len(product_uuids), "products_synced_now": len(synced), "synced_sample": synced}


# --------------------------
# CALCULATOR (DB-backed)
# --------------------------

@app.get("/calc/doorhangers")
def calc_doorhangers(
    product_uuid: str,
    runsize: str,
    colorspec: str,
    markup_pct: float = DEFAULT_MARKUP_PCT,
    db: Session = Depends(get_db),
):
    """
    DB-backed price lookup:
    - finds matching base price row by runsize + colorspec (human readable)
    - returns cost + sell price with markup
    """
    row = (
        db.query(BasePriceRow)
        .filter(BasePriceRow.product_uuid == product_uuid)
        .filter(BasePriceRow.runsize == runsize)
        .filter(BasePriceRow.colorspec == colorspec)
        .first()
    )

    if not row:
        return {"ok": False, "error": "no_price_found_in_db", "product_uuid": product_uuid, "runsize": runsize, "colorspec": colorspec}

    cost = Decimal(str(row.product_baseprice))
    sell = cost * (Decimal("1.0") + Decimal(str(markup_pct)))

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsize": runsize,
        "colorspec": colorspec,
        "cost": float(cost),
        "markup_pct": markup_pct,
        "sell": float(sell),
        "base_price_uuid": row.base_price_uuid,
    }
