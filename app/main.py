import json
from decimal import Decimal

from fastapi import FastAPI, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.db import init_db, get_db, db_ping
from app.models import Category, Product, ProductCategory, ProductDetail, BasePriceRow
from app.fourover_client import FourOverClient
from app.config import FOUR_OVER_BASE_URL, FOUR_OVER_API_PREFIX

app = FastAPI(title="catdi-4over-connector", version="v2-stable-sync")
client = FourOverClient()


# -----------------------
# Health + Debug
# -----------------------

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "v2-stable-sync"}


@app.get("/debug/auth")
def debug_auth():
    return {
        "FOUR_OVER_BASE_URL": FOUR_OVER_BASE_URL,
        "FOUR_OVER_API_PREFIX": FOUR_OVER_API_PREFIX,
        "FOUR_OVER_APIKEY_present": bool(client.ready),
        "FOUR_OVER_PRIVATE_KEY_present": bool(client.ready),
        "FOUR_OVER_TIMEOUT": "30",
    }


@app.get("/db/ping")
def ping_db():
    ok, detail = db_ping()
    if not ok:
        # return 500 but with actual error detail so we can fix it fast
        raise HTTPException(status_code=500, detail={"ok": False, "error": detail})
    return {"ok": True, "db": "ok"}


@app.post("/db/init")
def db_init():
    init_db()
    return {"ok": True, "message": "DB initialized (tables created if missing)"}


# -----------------------
# 4over passthroughs
# -----------------------

@app.get("/4over/whoami")
def whoami():
    # whoami is NOT under printproducts
    code, data = client.get("whoami", use_prefix=False)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories")
def categories(max: int = Query(50), offset: int = Query(0)):
    code, data = client.get("categories", params={"max": max, "offset": offset}, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(50), offset: int = Query(0)):
    path = f"categories/{category_uuid}/products"
    code, data = client.get(path, params={"max": max, "offset": offset}, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    path = f"products/{product_uuid}"
    code, data = client.get(path, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = Query(200), offset: int = Query(0)):
    path = f"products/{product_uuid}/baseprices"
    code, data = client.get(path, params={"max": max, "offset": offset}, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": data}
    return {"ok": True, "data": data}


# -----------------------
# SYNC to DB
# -----------------------

@app.post("/sync/categories")
def sync_categories(db: Session = Depends(get_db), max: int = Query(50), offset: int = Query(0)):
    code, payload = client.get("categories", params={"max": max, "offset": offset}, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    entities = payload.get("entities", []) or []
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
    path = f"categories/{category_uuid}/products"
    code, payload = client.get(path, params={"max": max, "offset": offset}, use_prefix=True)
    if code >= 400:
        return {"ok": False, "http_code": code, "data": payload}

    entities = payload.get("entities", []) or []
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

        existing = db.query(ProductCategory).filter_by(product_uuid=puid, category_uuid=category_uuid).first()
        if not existing:
            db.add(ProductCategory(product_uuid=puid, category_uuid=category_uuid))
            links += 1

    db.commit()
    return {"ok": True, "products_upserted": upserts, "links_added": links, "page": payload.get("currentPage"), "totalResults": payload.get("totalResults")}


@app.post("/sync/product/{product_uuid}")
def sync_product_detail(product_uuid: str, db: Session = Depends(get_db)):
    code, payload = client.get(f"products/{product_uuid}", use_prefix=True)
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
        code, payload = client.get(
            f"products/{product_uuid}/baseprices",
            params={"max": max_page, "offset": offset},
            use_prefix=True
        )
        if code >= 400:
            return {"ok": False, "http_code": code, "data": payload, "offset": offset}

        entities = payload.get("entities", []) or []
        if not entities:
            break

        for r in entities:
            base_price_uuid = r.get("base_price_uuid")
            if not base_price_uuid:
                continue

            # Use base_price_uuid as primary key so inserts are idempotent
            existing = db.get(BasePriceRow, base_price_uuid)
            if not existing:
                existing = BasePriceRow(
                    id=base_price_uuid,
                    base_price_uuid=base_price_uuid,
                    product_uuid=product_uuid,
                    raw_json="{}",
                )
                db.add(existing)
                inserted += 1
            else:
                updated += 1

            existing.product_baseprice = Decimal(str(r.get("product_baseprice", "0") or "0"))
            existing.runsize_uuid = r.get("runsize_uuid")
            existing.runsize = r.get("runsize")
            existing.colorspec_uuid = r.get("colorspec_uuid")
            existing.colorspec = r.get("colorspec")
            existing.can_group_ship = r.get("can_group_ship")
            existing.raw_json = json.dumps(r)

        db.commit()

        total = payload.get("totalResults")
        offset += len(entities)
        if total is not None and offset >= int(total):
            break

    return {"ok": True, "product_uuid": product_uuid, "inserted": inserted, "updated": updated}


@app.post("/sync/doorhangers")
def sync_doorhangers(db: Session = Depends(get_db), sample_n: int = Query(10)):
    """
    Door Hangers category_uuid (your known one):
    5cacc269-e6a8-472d-91d6-792c4584cae8

    This syncs all product stubs + links,
    then syncs details + base prices for a sample subset (default 10).
    """
    category_uuid = "5cacc269-e6a8-472d-91d6-792c4584cae8"

    max_page = 50
    offset = 0
    product_uuids = []

    while True:
        code, payload = client.get(
            f"categories/{category_uuid}/products",
            params={"max": max_page, "offset": offset},
            use_prefix=True
        )
        if code >= 400:
            return {"ok": False, "http_code": code, "data": payload, "offset": offset}

        entities = payload.get("entities", []) or []
        if not entities:
            break

        for p in entities:
            product_uuids.append(p["product_uuid"])

        # store product stubs + category link
        sync_category_products(category_uuid, db, max=max_page, offset=offset)

        total = payload.get("totalResults")
        offset += len(entities)
        if total is not None and offset >= int(total):
            break

    synced = []
    for puid in product_uuids[: max(0, int(sample_n))]:
        sync_product_detail(puid, db)
        sync_product_base_prices(puid, db)
        synced.append(puid)

    return {
        "ok": True,
        "category_uuid": category_uuid,
        "products_found": len(product_uuids),
        "products_synced_now": len(synced),
        "synced_sample": synced,
    }
