from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_db
from models import Product, ProductOptionGroup, ProductOptionValue
from fourover_client import fourover_get

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


@router.get("/tester")
def tester(product_uuid: str = Query(...), db: Session = Depends(get_db)):
    """
    Fetch ONE product detail + option groups from 4over and return it.
    Doesn't write to DB unless you call /import.
    """
    # product endpoint pattern:
    # /printproducts/products/{product_uuid}
    prod_res = fourover_get(f"/printproducts/products/{product_uuid}")
    if not prod_res["ok"]:
        return prod_res

    # options endpoint pattern:
    # /printproducts/products/{product_uuid}/options
    opt_res = fourover_get(f"/printproducts/products/{product_uuid}/options")
    if not opt_res["ok"]:
        return {"product": prod_res["response"], "options": opt_res, "debug": {"product": prod_res.get("debug"), "options": opt_res.get("debug")}}

    product_payload = prod_res["response"]
    option_payload = opt_res["response"]

    # Normalize option groups list
    groups = option_payload.get("entities") or option_payload.get("data") or option_payload
    if not isinstance(groups, list):
        groups = option_payload.get("option_groups") or []

    # Return in the shape you were already using
    return {
        "product": {
            "product_uuid": product_payload.get("product_uuid") or product_uuid,
            "product_code": product_payload.get("product_code"),
            "product_description": product_payload.get("product_description") or product_payload.get("description"),
        },
        "option_groups": groups,
        "debug": {"product": prod_res.get("debug"), "options": opt_res.get("debug")},
    }


@router.post("/import/{product_uuid}")
def import_one(product_uuid: str, db: Session = Depends(get_db)):
    """
    Imports one product + its option groups/values into DB.
    """
    prod_res = fourover_get(f"/printproducts/products/{product_uuid}")
    if not prod_res["ok"]:
        return prod_res

    opt_res = fourover_get(f"/printproducts/products/{product_uuid}/options")
    if not opt_res["ok"]:
        return opt_res

    p = prod_res["response"]
    groups = opt_res["response"].get("entities") or opt_res["response"].get("data") or opt_res["response"]
    if not isinstance(groups, list):
        groups = opt_res["response"].get("option_groups") or []

    # Upsert product
    row = db.query(Product).filter(Product.product_uuid == product_uuid).one_or_none()
    if not row:
        row = Product(product_uuid=product_uuid)
        db.add(row)

    row.product_code = p.get("product_code")
    row.product_description = p.get("product_description") or p.get("description")
    db.commit()

    # Clear existing groups for this product (keeps it clean / prevents duplicates)
    db.query(ProductOptionValue).filter(
        ProductOptionValue.group_id.in_(
            db.query(ProductOptionGroup.id).filter(ProductOptionGroup.product_uuid == product_uuid)
        )
    ).delete(synchronize_session=False)
    db.query(ProductOptionGroup).filter(ProductOptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.commit()

    # Insert fresh groups + values
    imported_groups = 0
    imported_values = 0

    for g in groups:
        g_uuid = g.get("product_option_group_uuid") or g.get("uuid")
        if not g_uuid:
            continue

        g_row = ProductOptionGroup(
            product_uuid=product_uuid,
            product_option_group_uuid=g_uuid,
            name=g.get("name"),
            minoccurs=str(g.get("minoccurs")) if g.get("minoccurs") is not None else None,
            maxoccurs=str(g.get("maxoccurs")) if g.get("maxoccurs") is not None else None,
        )
        db.add(g_row)
        db.flush()  # get g_row.id

        values = g.get("values") or []
        for v in values:
            v_row = ProductOptionValue(
                group_id=g_row.id,
                value_uuid=v.get("value_uuid") or v.get("uuid"),
                value=v.get("value"),
                description=v.get("description"),
            )
            db.add(v_row)
            imported_values += 1

        imported_groups += 1

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "imported_groups": imported_groups,
        "imported_values": imported_values,
        "debug": {"product": prod_res.get("debug"), "options": opt_res.get("debug")},
    }
