# routes_catalog.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db import get_db, CatalogSize, CatalogLine, CatalogProduct

router = APIRouter(prefix="/catalog", tags=["catalog"])

@router.get("/sizes")
def sizes(db: Session = Depends(get_db)):
    rows = db.query(CatalogSize).order_by(CatalogSize.display.asc()).all()
    return [{"id": r.id, "display": r.display} for r in rows]

@router.get("/lines")
def lines(size_id: int, family: str = "Business Cards", db: Session = Depends(get_db)):
    # All lines that exist for that family + size
    q = (
        db.query(CatalogLine.id, CatalogLine.name)
        .join(CatalogProduct, CatalogProduct.line_id == CatalogLine.id)
        .filter(CatalogProduct.size_id == size_id)
        .filter(CatalogLine.family == family)
        .distinct()
        .order_by(CatalogLine.name.asc())
    )
    return [{"id": row.id, "name": row.name} for row in q.all()]

@router.get("/resolve")
def resolve(size_id: int, line_id: int, db: Session = Depends(get_db)):
    # Returns the actual 4over product(s) behind the selection
    products = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.size_id == size_id, CatalogProduct.line_id == line_id)
        .order_by(CatalogProduct.product_code.asc())
        .all()
    )
    if not products:
        raise HTTPException(status_code=404, detail="No products for selection")

    return [{
        "product_uuid": p.product_uuid,
        "product_code": p.product_code,
        "description": p.description,
    } for p in products]
