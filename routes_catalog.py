from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_db
from models import Category, Product
from fourover_client import fourover_get

router = APIRouter(prefix="", tags=["catalog"])


@router.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute("SELECT 1")
    return {"ok": True}


@router.get("/4over/whoami")
def whoami():
    # 4over endpoint shown in your logs
    return fourover_get("/whoami")


@router.get("/categories")
def categories(db: Session = Depends(get_db), save: bool = Query(default=False)):
    """
    Lists categories. If save=true, stores them in DB (upsert).
    """
    res = fourover_get("/printproducts/categories")
    if not res["ok"]:
        return res

    entities = res["response"].get("entities") or res["response"].get("data") or res["response"]
    if not isinstance(entities, list):
        return {"ok": False, "http_code": res["http_code"], "response": res["response"], "debug": res.get("debug")}

    if save:
        for c in entities:
            uuid = c.get("category_uuid")
            if not uuid:
                continue
            row = db.query(Category).filter(Category.category_uuid == uuid).one_or_none()
            if not row:
                row = Category(category_uuid=uuid)
                db.add(row)
            row.category_name = c.get("category_name")
            row.category_description = c.get("category_description")
        db.commit()

    return {"ok": True, "count": len(entities), "entities": entities, "debug": res.get("debug")}


@router.get("/categories/{category_uuid}/products")
def category_products(category_uuid: str, db: Session = Depends(get_db), save: bool = Query(default=False)):
    """
    Lists products in a category. If save=true, stores in DB (upsert).
    """
    res = fourover_get(f"/printproducts/categories/{category_uuid}/products")
    if not res["ok"]:
        return res

    entities = res["response"].get("entities") or res["response"].get("data") or res["response"]
    if not isinstance(entities, list):
        return {"ok": False, "http_code": res["http_code"], "response": res["response"], "debug": res.get("debug")}

    if save:
        # Ensure category exists (optional)
        cat = db.query(Category).filter(Category.category_uuid == category_uuid).one_or_none()
        if not cat:
            cat = Category(category_uuid=category_uuid, category_name=None)
            db.add(cat)
            db.commit()

        for p in entities:
            puid = p.get("product_uuid")
            if not puid:
                continue
            row = db.query(Product).filter(Product.product_uuid == puid).one_or_none()
            if not row:
                row = Product(product_uuid=puid)
                db.add(row)
            row.product_code = p.get("product_code")
            row.product_description = p.get("product_description")
            row.category_uuid = category_uuid
        db.commit()

    return {"ok": True, "count": len(entities), "entities": entities, "debug": res.get("debug")}
