# pricing_tester.py
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import get_db
from models_pricing import (
    PricingProduct,
    PricingOptionGroup,
    PricingOption,
    PricingBasePrice,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])


# ---------------------------
# IMPORT FULL PRICING BUNDLE
# ---------------------------

@router.post("/import/{product_uuid}")
def import_pricing_bundle(
    product_uuid: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    product = payload.get("product")
    optiongroups = payload.get("optiongroups")
    baseprices = payload.get("baseprices")

    if not product or not optiongroups or not baseprices:
        raise HTTPException(status_code=400, detail="Payload must include product, optiongroups, baseprices")

    if product.get("product_uuid") != product_uuid:
        raise HTTPException(status_code=400, detail="Product UUID mismatch")

    # ---- Upsert product
    p = db.get(PricingProduct, product_uuid)
    if not p:
        p = PricingProduct(
            product_uuid=product_uuid,
            product_code=product.get("product_code"),
            product_description=product.get("product_description"),
        )
        db.add(p)
    else:
        p.product_code = product.get("product_code")
        p.product_description = product.get("product_description")

    # ---- Clean old data (SAFE per product)
    group_ids = [
        g[0] for g in db.query(PricingOptionGroup.product_option_group_uuid)
        .filter(PricingOptionGroup.product_uuid == product_uuid)
        .all()
    ]

    if group_ids:
        db.query(PricingOption).filter(
            PricingOption.group_uuid.in_(group_ids)
        ).delete(synchronize_session=False)

    db.query(PricingOptionGroup).filter(
        PricingOptionGroup.product_uuid == product_uuid
    ).delete(synchronize_session=False)

    db.query(PricingBasePrice).filter(
        PricingBasePrice.product_uuid == product_uuid
    ).delete(synchronize_session=False)

    # ---- Insert option groups + options
    for g in optiongroups.get("entities", []):
        group_uuid = g.get("product_option_group_uuid")
        if not group_uuid:
            continue

        grp = PricingOptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            name=g.get("name") or "",
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)

        for opt in g.get("values", []) or []:
            db.add(PricingOption(
                option_uuid=opt.get("product_option_value_uuid"),
                group_uuid=group_uuid,
                option_name=opt.get("name"),
                option_description=opt.get("description"),
                runsize_uuid=opt.get("runsize_uuid"),
                runsize=opt.get("runsize"),
                colorspec_uuid=opt.get("colorspec_uuid"),
                colorspec=opt.get("colorspec"),
            ))

    # ---- Insert base price matrix
    for bp in baseprices.get("entities", []):
        db.add(PricingBasePrice(
            base_price_uuid=bp.get("base_price_uuid"),
            product_uuid=product_uuid,
            product_baseprice=_to_decimal(bp.get("product_baseprice")),
            runsize_uuid=bp.get("runsize_uuid"),
            runsize=bp.get("runsize"),
            colorspec_uuid=bp.get("colorspec_uuid"),
            colorspec=bp.get("colorspec"),
            can_group_ship=bool(bp.get("can_group_ship", False)),
        ))

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "groups": len(optiongroups.get("entities", [])),
        "prices": len(baseprices.get("entities", [])),
    }


# ---------------------------
# LIST PRODUCTS
# ---------------------------

@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    rows = db.execute(select(PricingProduct)).scalars().all()
    return [
        {
            "product_uuid": r.product_uuid,
            "product_code": r.product_code,
            "product_description": r.product_description,
        }
        for r in rows
    ]


# ---------------------------
# PRODUCT CONFIG
# ---------------------------

@router.get("/product/{product_uuid}/config")
def product_config(product_uuid: str, db: Session = Depends(get_db)):
    p = db.get(PricingProduct, product_uuid)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    groups = db.execute(
        select(PricingOptionGroup).where(PricingOptionGroup.product_uuid == product_uuid)
    ).scalars().all()

    out_groups = []
    for g in groups:
        options = db.execute(
            select(PricingOption).where(PricingOption.group_uuid == g.product_option_group_uuid)
        ).scalars().all()

        out_groups.append({
            "group_uuid": g.product_option_group_uuid,
            "name": g.name,
            "minoccurs": g.minoccurs,
            "maxoccurs": g.maxoccurs,
            "options": [
                {
                    "option_uuid": o.option_uuid,
                    "option_name": o.option_name,
                    "runsize_uuid": o.runsize_uuid,
                    "runsize": o.runsize,
                    "colorspec_uuid": o.colorspec_uuid,
                    "colorspec": o.colorspec,
                }
                for o in options
            ],
        })

    return {
        "product": {
            "product_uuid": p.product_uuid,
            "product_code": p.product_code,
            "product_description": p.product_description,
        },
        "groups": out_groups,
    }


# ---------------------------
# PRICE MATRIX (IMPORTANT)
# ---------------------------

@router.get("/product/{product_uuid}/matrix")
def product_matrix(product_uuid: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(PricingBasePrice).where(PricingBasePrice.product_uuid == product_uuid)
    ).scalars().all()

    runsizes = {}
    colorspecs = {}

    for r in rows:
        if r.runsize_uuid:
            runsizes[r.runsize_uuid] = r.runsize
        if r.colorspec_uuid:
            colorspecs[r.colorspec_uuid] = r.colorspec

    return {
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in runsizes.items()],
        "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspecs.items()],
        "count_prices": len(rows),
    }


# ---------------------------
# PRICE LOOKUP
# ---------------------------

@router.get("/price")
def get_price(
    product_uuid: str,
    runsize_uuid: str,
    colorspec_uuid: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(PricingBasePrice).where(
            PricingBasePrice.product_uuid == product_uuid,
            PricingBasePrice.runsize_uuid == runsize_uuid,
            PricingBasePrice.colorspec_uuid == colorspec_uuid,
        )
    ).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail="No price for that combo")

    return {
        "product_uuid": product_uuid,
        "runsize_uuid": runsize_uuid,
        "colorspec_uuid": colorspec_uuid,
        "base_price": float(row.product_baseprice),
        "runsize": row.runsize,
        "colorspec": row.colorspec,
    }


# ---------------------------
# SIMPLE TESTER UI
# ---------------------------

@router.get("/tester/{product_uuid}", response_class=HTMLResponse)
def tester_ui(product_uuid: str):
    return HTMLResponse(f"""
<!doctype html>
<html>
<head>
  <title>Pricing Tester</title>
</head>
<body>
  <h2>Pricing Tester</h2>
  <p>Product UUID: {product_uuid}</p>
  <button onclick="load()">Load</button>
  <br/><br/>
  <select id="runsize"></select>
  <select id="colorspec"></select>
  <button onclick="price()">Get Price</button>
  <pre id="out"></pre>

<script>
async function load() {{
  const m = await fetch('/pricing/product/{product_uuid}/matrix').then(r=>r.json());
  document.getElementById('runsize').innerHTML =
    m.runsizes.map(r=>`<option value="${{r.runsize_uuid}}">${{r.runsize}}</option>`).join('');
  document.getElementById('colorspec').innerHTML =
    m.colorspecs.map(c=>`<option value="${{c.colorspec_uuid}}">${{c.colorspec}}</option>`).join('');
}}

async function price() {{
  const r = document.getElementById('runsize').value;
  const c = document.getElementById('colorspec').value;
  const res = await fetch(`/pricing/price?product_uuid={product_uuid}&runsize_uuid=${{r}}&colorspec_uuid=${{c}}`);
  document.getElementById('out').textContent = JSON.stringify(await res.json(), null, 2);
}}
</script>
</body>
</html>
""")


def _to_int(v):
    try:
        return int(v) if v is not None else None
    except:
        return None


def _to_decimal(v):
    return str(v) if v is not None else "0"
