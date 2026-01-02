import json
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import SERVICE_NAME
from app.db import Base, engine, get_db
from app.models import Category, Product, PriceBlob
from app.fourover_client import FourOverClient

app = FastAPI(title=SERVICE_NAME)

# Create tables at startup
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"ok": True, "service": SERVICE_NAME}


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute("SELECT 1")
    return {"ok": True}


# ----------------------------
# 4OVER passthrough endpoints
# ----------------------------

@app.get("/4over/categories")
def four_over_categories(max: int = 50, offset: int = 0):
    c = FourOverClient()
    status, data = c.get("/printproducts/categories", {"max": max, "offset": offset})
    if status >= 400:
        raise HTTPException(status_code=status, detail=data)
    return {"ok": True, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def four_over_category_products(category_uuid: str, max: int = 50, offset: int = 0):
    c = FourOverClient()
    path = f"/printproducts/categories/{category_uuid}/products"
    status, data = c.get(path, {"max": max, "offset": offset})
    if status >= 400:
        raise HTTPException(status_code=status, detail=data)
    return {"ok": True, "data": data}


@app.get("/4over/products/{product_uuid}")
def four_over_product(product_uuid: str):
    c = FourOverClient()
    path = f"/printproducts/products/{product_uuid}"
    status, data = c.get(path)
    if status >= 400:
        raise HTTPException(status_code=status, detail=data)
    return {"ok": True, "data": data}


# ----------------------------
# SYNC endpoints (DB caching)
# ----------------------------

@app.post("/sync/categories")
def sync_categories(max: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    c = FourOverClient()
    status, payload = c.get("/printproducts/categories", {"max": max, "offset": offset})
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload)

    entities = (payload or {}).get("entities", [])
    upserted = 0

    for e in entities:
        uuid = e.get("category_uuid")
        if not uuid:
            continue

        row = db.get(Category, uuid)
        if not row:
            row = Category(category_uuid=uuid)
            db.add(row)

        row.category_name = e.get("category_name") or ""
        row.category_description = e.get("category_description")
        row.products_url = e.get("products")
        upserted += 1

    db.commit()
    return {"ok": True, "upserted": upserted, "max": max, "offset": offset}


@app.post("/sync/category/{category_uuid}/products")
def sync_category_products(
    category_uuid: str,
    max: int = 50,
    offset: int = 0,
    pull_details: bool = True,
    pull_prices: bool = False,
    price_limit: int = 40,  # safety cap for first run
    db: Session = Depends(get_db),
):
    c = FourOverClient()
    path = f"/printproducts/categories/{category_uuid}/products"
    status, payload = c.get(path, {"max": max, "offset": offset})
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload)

    entities = (payload or {}).get("entities", [])
    upserted = 0

    for e in entities:
        puuid = e.get("product_uuid")
        if not puuid:
            continue

        row = db.get(Product, puuid)
        if not row:
            row = Product(product_uuid=puuid)
            db.add(row)

        row.product_code = e.get("product_code")
        row.product_description = e.get("product_description")
        row.category_uuid = category_uuid
        upserted += 1

        if pull_details or pull_prices:
            _sync_one_product(db=db, client=c, product_uuid=puuid, pull_prices=pull_prices, price_limit=price_limit)

    db.commit()
    return {
        "ok": True,
        "category_uuid": category_uuid,
        "upserted_products": upserted,
        "pull_details": pull_details,
        "pull_prices": pull_prices,
        "max": max,
        "offset": offset,
    }


@app.post("/sync/product/{product_uuid}")
def sync_product(
    product_uuid: str,
    pull_prices: bool = False,
    price_limit: int = 40,
    db: Session = Depends(get_db),
):
    c = FourOverClient()
    _sync_one_product(db=db, client=c, product_uuid=product_uuid, pull_prices=pull_prices, price_limit=price_limit)
    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "pull_prices": pull_prices, "price_limit": price_limit}


def _sync_one_product(db: Session, client: FourOverClient, product_uuid: str, pull_prices: bool, price_limit: int):
    # Pull full product detail
    status, detail = client.get(f"/printproducts/products/{product_uuid}")
    if status >= 400:
        raise HTTPException(status_code=status, detail=detail)

    row = db.get(Product, product_uuid)
    if not row:
        row = Product(product_uuid=product_uuid)
        db.add(row)

    row.product_code = detail.get("product_code")
    row.product_description = detail.get("product_description")
    row.detail_json = json.dumps(detail)

    if not pull_prices:
        return

    # Collect option_prices URLs from detail JSON
    urls = []
    for og in detail.get("product_option_groups", []) or []:
        for opt in og.get("options", []) or []:
            u = opt.get("option_prices")
            if u:
                urls.append(u)

    # Deduplicate, cap
    urls = list(dict.fromkeys(urls))[: max(0, int(price_limit))]

    for u in urls:
        status2, price_json = client.get_by_full_url(u)
        if status2 >= 400:
            # keep going; don't kill whole sync
            continue

        db.add(
            PriceBlob(
                product_uuid=product_uuid,
                option_prices_url=u,
                price_json=json.dumps(price_json),
            )
        )


@app.get("/db/products/{product_uuid}")
def db_get_product(product_uuid: str, db: Session = Depends(get_db)):
    row = db.get(Product, product_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "ok": True,
        "product_uuid": row.product_uuid,
        "product_code": row.product_code,
        "product_description": row.product_description,
        "category_uuid": row.category_uuid,
        "has_detail_json": bool(row.detail_json),
    }


@app.get("/db/products/{product_uuid}/prices")
def db_get_prices(product_uuid: str, limit: int = 25, db: Session = Depends(get_db)):
    q = (
        db.query(PriceBlob)
        .filter(PriceBlob.product_uuid == product_uuid)
        .order_by(PriceBlob.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "ok": True,
        "product_uuid": product_uuid,
        "count": len(q),
        "items": [{"id": r.id, "url": r.option_prices_url, "fetched_at": r.fetched_at} for r in q],
    }
