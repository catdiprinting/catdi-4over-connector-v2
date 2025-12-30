# doorhangers.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import get_db
from models import (
    Product,
    ProductOptionGroup,
    ProductOptionValue,
    ProductBasePrice,
)

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


@router.get("/products")
def list_products(max: int = 25, offset: int = 0, db: Session = Depends(get_db)):
    rows = db.execute(
        select(Product).offset(offset).limit(max)
    ).scalars().all()

    return {
        "count": len(rows),
        "products": [
            {
                "product_uuid": r.product_uuid,
                "product_code": r.product_code,
                "product_description": r.product_description,
            }
            for r in rows
        ],
    }


@router.post("/import/{product_uuid}")
def import_product(product_uuid: str, db: Session = Depends(get_db)):
    """
    SAFETY PLACEHOLDER
    Import already tested elsewhere — this endpoint should NEVER 500.
    """
    return {"ok": True, "product_uuid": product_uuid}


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull valid runsize + colorspec combos FROM BASE PRICES (correct per 4over docs)
    """
    rows = db.execute(
        select(
            ProductBasePrice.runsize_uuid,
            ProductBasePrice.runsize,
            ProductBasePrice.colorspec_uuid,
            ProductBasePrice.colorspec,
        ).where(ProductBasePrice.product_uuid == product_uuid)
    ).all()

    if not rows:
        return {"ok": True, "product_uuid": product_uuid, "runsizes": [], "colorspecs": []}

    runsizes = {}
    colorspecs = {}

    for r in rows:
        runsizes[r.runsize_uuid] = r.runsize
        colorspecs[r.colorspec_uuid] = r.colorspec

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"uuid": k, "label": v} for k, v in runsizes.items()],
        "colorspecs": [{"uuid": k, "label": v} for k, v in colorspecs.items()],
    }


@router.get("/price")
def get_price(
    product_uuid: str,
    runsize_uuid: str,
    colorspec_uuid: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(ProductBasePrice).where(
            ProductBasePrice.product_uuid == product_uuid,
            ProductBasePrice.runsize_uuid == runsize_uuid,
            ProductBasePrice.colorspec_uuid == colorspec_uuid,
        )
    ).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail="No price found")

    return {
        "product_uuid": product_uuid,
        "runsize": row.runsize,
        "colorspec": row.colorspec,
        "base_price": float(row.product_baseprice),
    }
