# doorhangers.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, func

from db import get_db
from models import PricingProduct, PricingOptionGroup, PricingOption, PricingBasePrice
from fourover_client import get as four_get, FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, signature_for_method

# Door Hangers category UUID you were using:
DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


@router.get("/_debug/products")
def debug_products(max: int = 5, offset: int = 0):
    # shows exactly what URL we call (helpful for auth debugging)
    path = f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products"
    sig = signature_for_method("GET")
    full_url = f"{FOUR_OVER_BASE_URL}{path}?max={max}&offset={offset}&apikey={FOUR_OVER_APIKEY}&signature={sig}"
    return {
        "base_url": FOUR_OVER_BASE_URL,
        "path": path,
        "query": {"max": max, "offset": offset, "apikey": FOUR_OVER_APIKEY, "signature": sig},
        "full_url": full_url,
    }


@router.get("/products")
def list_category_products(max: int = 25, offset: int = 0):
    path = f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products"
    return four_get(path, {"max": max, "offset": offset})


@router.get("/product/{product_uuid}/optiongroups")
def product_optiongroups(product_uuid: str):
    return four_get(f"/printproducts/products/{product_uuid}/optiongroups")


@router.get("/product/{product_uuid}/baseprices")
def product_baseprices(product_uuid: str):
    return four_get(f"/printproducts/products/{product_uuid}/baseprices")


@router.post("/import/{product_uuid}")
def import_product_bundle(product_uuid: str, db: Session = Depends(get_db)):
    """
    Fetches product list entry (code/description) from category list,
    then optiongroups + baseprices from product endpoints, then stores them locally.
    """
    # 1) Get product info from category listing (cheap + consistent)
    prods = four_get(
        f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products",
        {"max": 200, "offset": 0},
    )
    match = None
    for p in prods.get("entities", []):
        if p.get("product_uuid") == product_uuid:
            match = p
            break
    if not match:
        raise HTTPException(status_code=404, detail="Product not found in doorhangers category list")

    # 2) Pull option groups + baseprices
    og = four_get(f"/printproducts/products/{product_uuid}/optiongroups")
    bp = four_get(f"/printproducts/products/{product_uuid}/baseprices")

    # 3) Upsert product
    existing = db.get(PricingProduct, product_uuid)
    if not existing:
        existing = PricingProduct(
            product_uuid=product_uuid,
            product_code=match.get("product_code"),
            product_description=match.get("product_description"),
        )
        db.add(existing)
    else:
        existing.product_code = match.get("product_code")
        existing.product_description = match.get("product_description")

    # 4) Clear old rows for this product
    group_ids = [g.get("product_option_group_uuid") for g in og.get("entities", []) if g.get("product_option_group_uuid")]

    if group_ids:
        db.execute(delete(PricingOption).where(PricingOption.group_uuid.in_(group_ids)))

    db.execute(delete(PricingOptionGroup).where(PricingOptionGroup.product_uuid == product_uuid))
    db.execute(delete(PricingBasePrice).where(PricingBasePrice.product_uuid == product_uuid))

    # 5) Insert option groups + options
    option_groups_count = 0
    option_values_count = 0

    for g in og.get("entities", []):
        group_uuid = g.get("product_option_group_uuid")
        if not group_uuid:
            continue

        # NOTE: some responses use "name", some use "product_option_group_name"
        name = g.get("name") or g.get("product_option_group_name") or ""

        grp = PricingOptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            name=name,
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)
        option_groups_count += 1

        # NOTE: some responses use "values", some use "options"
        values = g.get("values") or g.get("options") or []
        for v in values:
            opt_uuid = v.get("product_option_value_uuid") or v.get("option_uuid")
            if not opt_uuid:
                continue

            db.add(PricingOption(
                option_uuid=opt_uuid,
                group_uuid=group_uuid,
                option_name=v.get("name") or v.get("option_name") or "",
                option_description=v.get("option_description"),
                capi_name=v.get("capi_name"),
                capi_description=v.get("capi_description"),
                runsize_uuid=v.get("runsize_uuid"),
                runsize=v.get("runsize"),
                colorspec_uuid=v.get("colorspec_uuid"),
                colorspec=v.get("colorspec"),
            ))
            option_values_count += 1

    # 6) Insert baseprices matrix
    baseprices_count = 0
    for row in bp.get("entities", []):
        bpu = row.get("base_price_uuid")
        if not bpu:
            continue
        db.add(PricingBasePrice(
            base_price_uuid=bpu,
            product_uuid=product_uuid,
            product_baseprice=_to_decimal(row.get("product_baseprice")),
            runsize_uuid=row.get("runsize_uuid"),
            runsize=str(row.get("runsize")) if row.get("runsize") is not None else None,
            colorspec_uuid=row.get("colorspec_uuid"),
            colorspec=row.get("colorspec"),
            can_group_ship=bool(row.get("can_group_ship", False)),
        ))
        baseprices_count += 1

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "option_groups": option_groups_count,
        "option_values": option_values_count,
        "baseprices": baseprices_count,
    }


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    Returns distinct runsize/colorspec UUIDs FROM THE BASEPRICE TABLE.
    This fixes the “runsizes/colorspecs []” issue.
    """
    runs = db.execute(
        select(PricingBasePrice.runsize_uuid, PricingBasePrice.runsize)
        .where(PricingBasePrice.product_uuid == product_uuid)
        .where(PricingBasePrice.runsize_uuid.is_not(None))
        .group_by(PricingBasePrice.runsize_uuid, PricingBasePrice.runsize)
        .order_by(func.length(PricingBasePrice.runsize), PricingBasePrice.runsize)
    ).all()

    cols = db.execute(
        select(PricingBasePrice.colorspec_uuid, PricingBasePrice.colorspec)
        .where(PricingBasePrice.product_uuid == product_uuid)
        .where(PricingBasePrice.colorspec_uuid.is_not(None))
        .group_by(PricingBasePrice.colorspec_uuid, PricingBasePrice.colorspec)
        .order_by(PricingBasePrice.colorspec)
    ).all()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"uuid": r[0], "name": r[1]} for r in runs],
        "colorspecs": [{"uuid": c[0], "name": c[1]} for c in cols],
    }


@router.get("/price")
def get_price(product_uuid: str, runsize_uuid: str, colorspec_uuid: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(PricingBasePrice).where(
            PricingBasePrice.product_uuid == product_uuid,
            PricingBasePrice.runsize_uuid == runsize_uuid,
            PricingBasePrice.colorspec_uuid == colorspec_uuid,
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
        "base_price": float(row.product_baseprice),
        "can_group_ship": bool(row.can_group_ship),
    }


def _to_int(v):
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_decimal(v):
    if v is None:
        return "0"
    return str(v)
