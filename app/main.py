# app/main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime
import hashlib
import json

from .db import get_db, init_db
from .models import Category, Product, ProductBasePrice
from .fourover_client import FourOverClient

app = FastAPI(title="Catdi × 4over Connector", version="2.0.1")

# ---- Startup ----
@app.on_event("startup")
def startup():
    init_db()

def client() -> FourOverClient:
    # Lazy client creation so app can boot even if env vars are temporarily missing
    return FourOverClient()

# ---- Health ----
@app.get("/")
def root():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "v2"}

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True}

# ---- 4over passthroughs ----
@app.get("/4over/whoami")
def whoami():
    c = client()
    res = c.get("/whoami")
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)
    return {"ok": True, "data": res["data"]}

@app.get("/4over/categories")
def list_categories(max: int = 50, offset: int = 0):
    c = client()
    res = c.get("/printproducts/categories", params={"max": max, "offset": offset})
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)
    return {"ok": True, "data": res["data"]}

@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    c = client()
    path = f"/printproducts/categories/{category_uuid}/products"
    res = c.get(path, params={"max": max, "offset": offset})
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)
    return {"ok": True, "data": res["data"]}

@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    """
    Hydrated product detail: product + option groups (and options).
    (We store this whole JSON in DB as raw_json for calculators.)
    """
    c = client()
    base = c.get(f"/printproducts/products/{product_uuid}")
    if not base["ok"]:
        raise HTTPException(status_code=base["http_code"], detail=base)

    product = base["data"]

    og = c.get(f"/printproducts/products/{product_uuid}/optiongroups")
    if og["ok"] and isinstance(og["data"], dict) and "entities" in og["data"]:
        option_groups = og["data"]["entities"]
        # Load options for each group
        for g in option_groups:
            group_uuid = g.get("product_option_group_uuid") or g.get("productOptionGroupUuid") or g.get("uuid")
            if group_uuid:
                opts = c.get(f"/printproducts/products/{product_uuid}/optiongroups/{group_uuid}/options")
                if opts["ok"] and isinstance(opts["data"], dict) and "entities" in opts["data"]:
                    g["options"] = opts["data"]["entities"]
        product["product_option_groups"] = option_groups

    return {"ok": True, "data": product}

# These are the endpoints you tried (they were 404 on your deployed instance)
@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = 200, offset: int = 0):
    c = client()
    res = c.get(f"/printproducts/products/{product_uuid}/baseprices", params={"max": max, "offset": offset})
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)
    return {"ok": True, "data": res["data"]}

@app.get("/4over/products/{product_uuid}/option-groups")
def product_option_groups(product_uuid: str):
    c = client()
    res = c.get(f"/printproducts/products/{product_uuid}/optiongroups")
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)
    return {"ok": True, "data": res["data"]}

# ---- DB Sync ----
@app.post("/sync/category/{category_uuid}")
def sync_category(category_uuid: str, db: Session = Depends(get_db), max: int = 50, offset: int = 0):
    """
    Sync:
    - category record
    - products list in category
    - for each product: store product raw_json + base prices
    """
    c = client()

    # Pull category info (optional; safe even if you only have uuid)
    cat_row = db.get(Category, category_uuid)
    if not cat_row:
        cat_row = Category(category_uuid=category_uuid, category_name=None, category_description=None)
        db.add(cat_row)
        db.commit()

    # Fetch products for this category
    res = c.get(f"/printproducts/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    if not res["ok"]:
        raise HTTPException(status_code=res["http_code"], detail=res)

    entities = res["data"].get("entities", [])
    synced = 0
    for p in entities:
        puid = p.get("product_uuid")
        if not puid:
            continue
        sync_product(puid, db=db)  # re-use below
        synced += 1

    return {"ok": True, "category_uuid": category_uuid, "synced_products": synced}

@app.post("/sync/product/{product_uuid}")
def sync_product(product_uuid: str, db: Session = Depends(get_db)):
    """
    Stores:
    - Product (uuid, code, description, raw_json)
    - ProductBasePrice rows
    """
    c = client()

    # 1) Hydrated product JSON
    detail = product_detail(product_uuid)
    product_json = detail["data"]

    code = product_json.get("product_code")
    desc = product_json.get("product_description")

    row = db.get(Product, product_uuid)
    if not row:
        row = Product(
            product_uuid=product_uuid,
            product_code=code,
            product_description=desc,
            raw_json=json.dumps(product_json),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    else:
        row.product_code = code
        row.product_description = desc
        row.raw_json = json.dumps(product_json)
        row.updated_at = datetime.utcnow()

    db.commit()

    # 2) Base prices
    prices_res = c.get(f"/printproducts/products/{product_uuid}/baseprices", params={"max": 500, "offset": 0})
    if not prices_res["ok"]:
        raise HTTPException(status_code=prices_res["http_code"], detail=prices_res)

    entities = prices_res["data"].get("entities", [])

    # Clear old prices for this product (simple + safe for now)
    db.query(ProductBasePrice).filter(ProductBasePrice.product_uuid == product_uuid).delete()
    db.commit()

    inserted = 0
    for e in entities:
        # We build a deterministic UUID for the row from the JSON blob
        blob = json.dumps(e, sort_keys=True).encode("utf-8")
        base_price_uuid = hashlib.sha1(blob).hexdigest()

        db.add(
            ProductBasePrice(
                base_price_uuid=base_price_uuid,
                product_uuid=product_uuid,
                raw_json=json.dumps(e),
                updated_at=datetime.utcnow(),
            )
        )
        inserted += 1

    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "base_prices_inserted": inserted}
