# doorhangers.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, distinct

from db import get_db
from models import Product, OptionGroup, OptionValue, BasePrice
from fourover_client import FourOverClient

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])

# Door Hangers category UUID you’ve been using in logs:
DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"


def _to_int(v):
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


@router.get("/_debug/products")
def debug_products(max: int = 5, offset: int = 0):
    """
    Returns the *exact* upstream URL we are calling (with apikey/signature).
    Useful to verify signature behavior.
    """
    c = FourOverClient()
    return c.debug_get_url(
        f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products",
        {"max": max, "offset": offset},
    )


@router.get("/products")
def list_category_products(max: int = 20, offset: int = 0):
    """
    Proxy list: GET /printproducts/categories/{uuid}/products?max=&offset=
    """
    c = FourOverClient()
    resp = c.get(
        f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products",
        {"max": max, "offset": offset},
    )

    if resp.status_code >= 400:
        return {"ok": False, "status_code": resp.status_code, "error": _safe_json(resp)}

    return _safe_json(resp)


@router.get("/product/{product_uuid}/optiongroups")
def get_optiongroups(product_uuid: str):
    c = FourOverClient()
    resp = c.get(f"/printproducts/products/{product_uuid}/optiongroups")

    if resp.status_code >= 400:
        return {"ok": False, "status_code": resp.status_code, "error": _safe_json(resp)}

    return _safe_json(resp)


@router.get("/product/{product_uuid}/baseprices")
def get_baseprices(product_uuid: str):
    c = FourOverClient()
    resp = c.get(f"/printproducts/products/{product_uuid}/baseprices")

    if resp.status_code >= 400:
        return {"ok": False, "status_code": resp.status_code, "error": _safe_json(resp)}

    return _safe_json(resp)


@router.post("/import/{product_uuid}")
def import_product_bundle(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull product + optiongroups + baseprices from 4over and store in DB.
    """
    c = FourOverClient()

    # 1) product detail (we can pull it from products endpoint directly)
    p_resp = c.get(f"/printproducts/products/{product_uuid}")
    if p_resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"upstream": "product", "error": _safe_json(p_resp)})

    product = _safe_json(p_resp)

    # 2) optiongroups
    og_resp = c.get(f"/printproducts/products/{product_uuid}/optiongroups")
    if og_resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"upstream": "optiongroups", "error": _safe_json(og_resp)})
    optiongroups = _safe_json(og_resp)

    # 3) baseprices
    bp_resp = c.get(f"/printproducts/products/{product_uuid}/baseprices")
    if bp_resp.status_code >= 400:
        raise HTTPException(status_code=502, detail={"upstream": "baseprices", "error": _safe_json(bp_resp)})
    baseprices = _safe_json(bp_resp)

    # Normalize product fields (4over sometimes returns different keys depending route)
    product_code = product.get("product_code") or product.get("name") or ""
    product_desc = product.get("product_description") or product.get("description") or ""

    # Upsert product
    existing = db.get(Product, product_uuid)
    if not existing:
        existing = Product(product_uuid=product_uuid, product_code=product_code, product_description=product_desc)
        db.add(existing)
    else:
        existing.product_code = product_code
        existing.product_description = product_desc

    # Clear per-product rows
    # delete option values -> option groups -> baseprices
    group_ids = [g.get("product_option_group_uuid") for g in optiongroups.get("entities", []) if g.get("product_option_group_uuid")]
    if group_ids:
        db.query(OptionValue).filter(OptionValue.group_uuid.in_(group_ids)).delete(synchronize_session=False)

    db.query(OptionGroup).filter(OptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(BasePrice).filter(BasePrice.product_uuid == product_uuid).delete(synchronize_session=False)

    # Insert option groups + values
    groups_inserted = 0
    values_inserted = 0

    for g in optiongroups.get("entities", []):
        group_uuid = g.get("product_option_group_uuid")
        if not group_uuid:
            continue

        grp = OptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            name=g.get("name") or g.get("product_option_group_name") or "",
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)
        groups_inserted += 1

        # Some 4over payloads use "values", some use "options"
        values = g.get("values") or g.get("options") or []
        for v in values:
            val_uuid = v.get("product_option_value_uuid") or v.get("option_uuid")
            if not val_uuid:
                continue

            db.add(
                OptionValue(
                    product_option_value_uuid=val_uuid,
                    group_uuid=group_uuid,
                    name=v.get("name") or v.get("option_name") or "",
                    code=v.get("code") or v.get("capi_name") or "",
                    sort=_to_int(v.get("sort")),
                    runsize_uuid=v.get("runsize_uuid"),
                    runsize=v.get("runsize"),
                    colorspec_uuid=v.get("colorspec_uuid"),
                    colorspec=v.get("colorspec"),
                    turnaroundtime_uuid=v.get("turnaroundtime_uuid"),
                    turnaroundtime=v.get("turnaroundtime"),
                )
            )
            values_inserted += 1

    # Insert base prices
    prices_inserted = 0
    for bp in baseprices.get("entities", []):
        bpu = bp.get("base_price_uuid")
        if not bpu:
            continue

        db.add(
            BasePrice(
                base_price_uuid=bpu,
                product_uuid=product_uuid,
                product_baseprice=str(bp.get("product_baseprice") or "0"),
                runsize_uuid=bp.get("runsize_uuid"),
                runsize=str(bp.get("runsize") or ""),
                colorspec_uuid=bp.get("colorspec_uuid"),
                colorspec=str(bp.get("colorspec") or ""),
                can_group_ship=bool(bp.get("can_group_ship", False)),
            )
        )
        prices_inserted += 1

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "groups": groups_inserted,
        "values": values_inserted,
        "baseprices": prices_inserted,
    }


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    Returns distinct runsize_uuid/colorspec_uuid available in DB for that product.
    """
    p = db.get(Product, product_uuid)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found in DB (run /doorhangers/import/{product_uuid})")

    runs = db.execute(
        select(distinct(BasePrice.runsize_uuid), BasePrice.runsize).where(BasePrice.product_uuid == product_uuid)
    ).all()

    cols = db.execute(
        select(distinct(BasePrice.colorspec_uuid), BasePrice.colorspec).where(BasePrice.product_uuid == product_uuid)
    ).all()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": r[0], "runsize": r[1]} for r in runs if r[0]],
        "colorspecs": [{"colorspec_uuid": c[0], "colorspec": c[1]} for c in cols if c[0]],
    }
