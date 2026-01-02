import json
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import SERVICE_NAME, FOUR_OVER_BASE_URL, FOUR_OVER_API_PREFIX
from app.db import Base, engine, get_db
from app.models import Category, Product, PriceBlob
from app.fourover_client import FourOverClient

app = FastAPI(title=SERVICE_NAME, version="bridge")


# Create tables on boot (simple + reliable for now)
Base.metadata.create_all(bind=engine)


def client() -> FourOverClient:
    return FourOverClient()


@app.get("/health")
def health():
    return {"ok": True, "service": SERVICE_NAME}


@app.get("/ping")
def ping():
    return {"ok": True, "service": SERVICE_NAME, "phase": "bridge"}


@app.get("/debug/auth")
def debug_auth():
    return {
        "FOUR_OVER_BASE_URL": FOUR_OVER_BASE_URL,
        "FOUR_OVER_API_PREFIX": FOUR_OVER_API_PREFIX,
        "FOUR_OVER_APIKEY_present": True if __import__("app.config").config.FOUR_OVER_APIKEY else False,
        "FOUR_OVER_PRIVATE_KEY_present": True if __import__("app.config").config.FOUR_OVER_PRIVATE_KEY else False,
        "FOUR_OVER_TIMEOUT": str(__import__("app.config").config.FOUR_OVER_TIMEOUT),
    }


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {type(e).__name__}: {e}")


# ---------------------------
# 4OVER PROXY ENDPOINTS
# ---------------------------

@app.get("/4over/whoami")
def whoami():
    c = client()
    out = c.get("/whoami")
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)
    return {"ok": True, "data": out["data"]}


@app.get("/4over/categories")
def categories(max: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    c = client()
    out = c.get("/printproducts/categories", params={"max": max, "offset": offset})
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)
    return {"ok": True, "data": out["data"]}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    c = client()
    out = c.get(f"/printproducts/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)
    return {"ok": True, "data": out["data"]}


@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    """
    This returns product + option groups in one shot (what you pasted).
    """
    c = client()
    out = c.get(f"/printproducts/products/{product_uuid}")
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)
    return {"ok": True, "data": out["data"]}


@app.get("/4over/products/{product_uuid}/baseprices")
def product_base_prices(product_uuid: str):
    """
    Many products expose a base prices endpoint:
      /printproducts/products/{uuid}/baseprices
    """
    c = client()
    out = c.get(f"/printproducts/products/{product_uuid}/baseprices")
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)
    return {"ok": True, "data": out["data"]}


# ---------------------------
# DB SYNC ENDPOINTS (THE MONEY)
# ---------------------------

@app.post("/sync/categories")
def sync_categories(db: Session = Depends(get_db), max: int = 200, offset: int = 0):
    """
    Pull categories from 4over and upsert into DB.
    """
    c = client()
    out = c.get("/printproducts/categories", params={"max": max, "offset": offset})
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)

    payload = out["data"]
    entities = payload.get("entities", [])

    upserted = 0
    for e in entities:
        cu = e.get("category_uuid")
        if not cu:
            continue

        row = db.query(Category).filter(Category.category_uuid == cu).first()
        if not row:
            row = Category(category_uuid=cu, category_name=e.get("category_name") or cu)
            db.add(row)

        row.category_name = e.get("category_name") or row.category_name
        row.category_description = e.get("category_description")
        row.products_url = e.get("products")

        upserted += 1

    db.commit()
    return {"ok": True, "upserted": upserted, "totalResults": payload.get("totalResults")}


@app.post("/sync/categories/{category_uuid}/products")
def sync_category_products(category_uuid: str, db: Session = Depends(get_db), max: int = 200, offset: int = 0):
    """
    Pull products for a category and upsert.
    """
    c = client()
    out = c.get(f"/printproducts/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)

    payload = out["data"]
    entities = payload.get("entities", [])

    upserted = 0
    for e in entities:
        pu = e.get("product_uuid")
        if not pu:
            continue

        row = db.query(Product).filter(Product.product_uuid == pu).first()
        if not row:
            row = Product(product_uuid=pu)
            db.add(row)

        row.category_uuid = category_uuid
        row.product_code = e.get("product_code")
        row.product_description = e.get("product_description")
        row.full_product_path = e.get("full_product_path")
        row.option_groups_url = e.get("product_option_groups")
        row.base_prices_url = e.get("product_base_prices")

        upserted += 1

    db.commit()
    return {"ok": True, "category_uuid": category_uuid, "upserted": upserted, "totalResults": payload.get("totalResults")}


@app.post("/sync/products/{product_uuid}")
def sync_product_detail(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull full product detail (includes option groups) and store it as a JSON blob.
    This is the scalable approach: store raw payload first, normalize later.
    """
    c = client()
    out = c.get(f"/printproducts/products/{product_uuid}")
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)

    data = out["data"]
    json_text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    # upsert the product table too
    row = db.query(Product).filter(Product.product_uuid == product_uuid).first()
    if not row:
        row = Product(product_uuid=product_uuid)
        db.add(row)

    row.product_code = data.get("product_code")
    row.product_description = data.get("product_description")

    # store blob
    blob = db.query(PriceBlob).filter(
        PriceBlob.product_uuid == product_uuid,
        PriceBlob.blob_type == "product_detail",
        PriceBlob.fingerprint == "v1",
    ).first()

    if not blob:
        blob = PriceBlob(
            product_uuid=product_uuid,
            blob_type="product_detail",
            fingerprint="v1",
            json_text=json_text,
        )
        db.add(blob)
    else:
        blob.json_text = json_text

    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "stored": True}


@app.post("/sync/products/{product_uuid}/baseprices")
def sync_baseprices(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull baseprices and store as blob. This is what pricing calculators will use first.
    """
    c = client()
    out = c.get(f"/printproducts/products/{product_uuid}/baseprices")
    if not out["ok"]:
        raise HTTPException(status_code=out["http_code"], detail=out)

    data = out["data"]
    json_text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    blob = db.query(PriceBlob).filter(
        PriceBlob.product_uuid == product_uuid,
        PriceBlob.blob_type == "baseprices",
        PriceBlob.fingerprint == "v1",
    ).first()

    if not blob:
        blob = PriceBlob(
            product_uuid=product_uuid,
            blob_type="baseprices",
            fingerprint="v1",
            json_text=json_text,
        )
        db.add(blob)
    else:
        blob.json_text = json_text

    db.commit()
    return {"ok": True, "product_uuid": product_uuid, "stored": True}


@app.get("/db/products")
def db_products(db: Session = Depends(get_db), limit: int = 50):
    rows = db.query(Product).order_by(Product.id.desc()).limit(limit).all()
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "product_uuid": r.product_uuid,
                "product_code": r.product_code,
                "category_uuid": r.category_uuid,
                "product_description": r.product_description,
            }
            for r in rows
        ],
    }
