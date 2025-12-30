# doorhangers.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import get_db
from models import Product, ProductBasePrice

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


@router.get("/products")
def products(max: int = Query(5, ge=1, le=5000), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    rows = db.execute(select(Product).offset(offset).limit(max)).scalars().all()
    return {
        "count": len(rows),
        "products": [
            {
                "product_uuid": p.product_uuid,
                "product_code": p.product_code,
                "product_description": p.product_description,
            }
            for p in rows
        ],
    }


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            ProductBasePrice.runsize_uuid,
            ProductBasePrice.runsize,
            ProductBasePrice.colorspec_uuid,
            ProductBasePrice.colorspec,
        ).where(ProductBasePrice.product_uuid == product_uuid)
    ).all()

    runsizes = {}
    colorspecs = {}

    for r in rows:
        if r.runsize_uuid:
            runsizes[str(r.runsize_uuid)] = r.runsize
        if r.colorspec_uuid:
            colorspecs[str(r.colorspec_uuid)] = r.colorspec

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"uuid": k, "label": v} for k, v in runsizes.items()],
        "colorspecs": [{"uuid": k, "label": v} for k, v in colorspecs.items()],
        "rows": len(rows),
    }


@router.get("/price")
def price(product_uuid: str, runsize_uuid: str, colorspec_uuid: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(ProductBasePrice).where(
            ProductBasePrice.product_uuid == product_uuid,
            ProductBasePrice.runsize_uuid == runsize_uuid,
            ProductBasePrice.colorspec_uuid == colorspec_uuid,
        )
    ).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail="No base price found for that combo")

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsize_uuid": runsize_uuid,
        "colorspec_uuid": colorspec_uuid,
        "runsize": row.runsize,
        "colorspec": row.colorspec,
        "base_price": float(row.product_baseprice) if row.product_baseprice is not None else None,
    }
