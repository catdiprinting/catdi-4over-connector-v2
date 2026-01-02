# app/main.py
import json
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session

from .config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY
from .db import Base, engine, get_db
from .models import Category, Product
from .fourover_client import FourOverClient

app = FastAPI(title="Catdi 4over Connector", version="0.7.0")


@app.on_event("startup")
def startup():
    # Create tables (simple + fine for now)
    Base.metadata.create_all(bind=engine)


def client() -> FourOverClient:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        # Don't crash the app — just allow endpoints to return a clear message.
        # (This avoids Railway boot loops.)
        raise RuntimeError("Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")
    return FourOverClient(
        base_url=FOUR_OVER_BASE_URL or "https://api.4over.com",
        apikey=FOUR_OVER_APIKEY,
        private_key=FOUR_OVER_PRIVATE_KEY,
    )


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "version": app.version}


@app.get("/debug/auth")
def debug_auth():
    return {
        "base_url": FOUR_OVER_BASE_URL,
        "has_apikey": bool(FOUR_OVER_APIKEY),
        "has_private_key": bool(FOUR_OVER_PRIVATE_KEY),
    }


@app.get("/4over/whoami")
def whoami():
    try:
        c = client()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    return c.get("/whoami")


@app.get("/4over/categories")
def list_categories(store: bool = Query(True), db: Session = Depends(get_db)):
    """
    Pull categories live from 4over. Optionally store them.
    """
    try:
        c = client()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    data = c.get("/printproducts/categories")
    if not isinstance(data, dict) or "entities" not in data:
        return {"status": "error", "message": "Unexpected response", "raw": data}

    entities = data.get("entities", [])

    if store:
        for row in entities:
            cu = row.get("category_uuid")
            if not cu:
                continue
            existing = db.query(Category).filter(Category.category_uuid == cu).first()
            if existing:
                existing.category_name = row.get("category_name") or existing.category_name
                existing.category_description = row.get("category_description")
                existing.products_url = row.get("products")
            else:
                db.add(
                    Category(
                        category_uuid=cu,
                        category_name=row.get("category_name") or "",
                        category_description=row.get("category_description"),
                        products_url=row.get("products"),
                    )
                )
        db.commit()

    return {"count": len(entities), "entities": entities}


@app.get("/4over/category/{category_uuid}/products")
def category_products(category_uuid: str, store: bool = Query(True), db: Session = Depends(get_db)):
    """
    Pull products for a category. Optionally store them.
    """
    try:
        c = client()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    path = f"/printproducts/categories/{category_uuid}/products"
    data = c.get(path)

    if not isinstance(data, dict) or "entities" not in data:
        return {"status": "error", "message": "Unexpected response", "raw": data}

    entities = data.get("entities", [])

    if store:
        for p in entities:
            pu = p.get("product_uuid")
            if not pu:
                continue
            existing = (
                db.query(Product)
                .filter(Product.product_uuid == pu, Product.category_uuid == category_uuid)
                .first()
            )
            raw = json.dumps(p)
            if existing:
                existing.product_code = p.get("product_code")
                existing.product_description = p.get("product_description")
                existing.raw_json = raw
            else:
                db.add(
                    Product(
                        product_uuid=pu,
                        product_code=p.get("product_code"),
                        product_description=p.get("product_description"),
                        category_uuid=category_uuid,
                        raw_json=raw,
                    )
                )
        db.commit()

    return {"count": len(entities), "entities": entities}
