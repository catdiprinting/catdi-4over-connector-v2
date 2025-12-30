# pricing_tester.py
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from decimal import Decimal, InvalidOperation

from db import get_db
from models_pricing import (
    PricingProduct,
    PricingOptionGroup,
    PricingOption,
    PricingBasePrice,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])


# ---------------------------
# Helpers
# ---------------------------

def _to_int(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None


def _to_decimal(v):
    """
    Store numeric precisely, accept string numbers from 4over.
    Returns Decimal.
    """
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal("0")


# ---------------------------
# Import (per product)
# ---------------------------

@router.post("/import/{product_uuid}")
def import_pricing_bundle(
    product_uuid: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """
    Import a full pricing bundle for ONE product.
    Payload format:
      {
        "product": {...},
        "optiongroups": {... full optiongroups response ...},
        "baseprices": {... full baseprices response ...}
      }
    """
    product = payload.get("product")
    optiongroups = payload.get("optiongroups")
    baseprices = payload.get("baseprices")

    if not product or not optiongroups or not baseprices:
        raise HTTPException(
            status_code=400,
            detail="Payload must include: product, optiongroups, baseprices",
        )

    if str(product.get("product_uuid")) != str(product_uuid):
        raise HTTPException(
            status_code=400,
            detail="product_uuid in URL does not match payload.product.product_uuid",
        )

    # Upsert product
    existing = db.get(PricingProduct, product_uuid)
    if not existing:
        existing = PricingProduct(
            product_uuid=product_uuid,
            product_code=product.get("product_code"),
            product_description=product.get("product_description"),
        )
        db.add(existing)
    else:
        existing.product_code = product.get("product_code")
        existing.product_description = product.get("product_description")

    # ---- Clear old data for THIS product (safe re-import) ----
    group_ids = [
        r[0]
        for r in db.query(PricingOptionGroup.product_option_group_uuid)
        .filter(PricingOptionGroup.product_uuid == product_uuid)
        .all()
    ]

    if group_ids:
        db.query(PricingOption).filter(PricingOption.group_uuid.in_(group_ids)).delete(
            synchronize_session=False
        )

    db.query(PricingOptionGroup).filter(PricingOptionGroup.product_uuid == product_uuid).delete(
        synchronize_session=False
    )
    db.query(PricingBasePrice).filter(PricingBasePrice.product_uuid == product_uuid).delete(
        synchronize_session=False
    )

    # ---- Insert option groups + options ----
    groups = optiongroups.get("entities", []) or []
    for g in groups:
        group_uuid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
        if not group_uuid:
            continue

        # 4over sometimes uses different keys; support a few
        group_name = (
            g.get("name")
            or g.get("product_option_group_name")
            or g.get("option_group_name")
            or ""
        )

        grp = PricingOptionGroup(
            product_option_group_uuid=str(group_uuid),
            product_uuid=str(product_uuid),
            name=str(group_name),
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)

        values = g.get("values") or g.get("options") or []
        if isinstance(values, list):
            for opt in values:
                option_uuid = (
                    opt.get("product_option_value_uuid")
                    or opt.get("option_value_uuid")
                    or opt.get("option_uuid")
                    or opt.get("uuid")
                )
                if not option_uuid:
                    continue

                option_name = (
                    opt.get("name")
                    or opt.get("option_name")
                    or ""
                )

                db.add(
                    PricingOption(
                        option_uuid=str(option_uuid),
                        group_uuid=str(group_uuid),
                        option_name=str(option_name),
                        option_description=opt.get("option_description") or opt.get("description"),
                        capi_name=opt.get("capi_name"),
                        capi_description=opt.get("capi_description"),
                        runsize_uuid=opt.get("runsize_uuid"),
                        runsize=opt.get("runsize"),
                        colorspec_uuid=opt.get("colorspec_uuid"),
                        colorspec=opt.get("colorspec"),
                    )
                )

    # ---- Insert base prices (matrix) ----
    price_entities = baseprices.get("entities", []) or []
    for bp in price_entities:
        base_uuid = bp.get("base_price_uuid") or bp.get("product_baseprice_uuid") or bp.get("uuid")
        if not base_uuid:
            continue

        # 4over uses product_baseprice in your response
        price_val = bp.get("product_baseprice") or bp.get("price")

        db.add(
            PricingBasePrice(
                base_price_uuid=str(base_uuid),
                product_uuid=str(product_uuid),
                product_baseprice=_to_decimal(price_val),
                runsize_uuid=bp.get("runsize_uuid"),
                runsize=bp.get("runsize"),
                colorspec_uuid=bp.get("colorspec_uuid"),
                colorspec=bp.get("colorspec"),
                can_group_ship=bool(bp.get("can_group_ship", False)),
            )
        )

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "groups": len(groups),
        "prices": len(price_entities),
    }


# ---------------------------
# Read APIs
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

        out_groups.append(
            {
                "group_uuid": g.product_option_group_uuid,
                "name": g.name,
                "minoccurs": g.minoccurs,
                "maxoccurs": g.maxoccurs,
                "options": [
                    {
                        "option_uuid": o.option_uuid,
                        "option_name": o.option_name,
                        "option_description": o.option_description,
                        "runsize_uuid": o.runsize_uuid,
                        "runsize": o.runsize,
                        "colorspec_uuid": o.colorspec_uuid,
                        "colorspec": o.colorspec,
                    }
                    for o in options
                ],
            }
        )

    return {
        "product": {
            "product_uuid": p.product_uuid,
            "product_code": p.product_code,
            "product_description": p.product_description,
        },
        "groups": out_groups,
    }


@router.get("/product/{product_uuid}/matrix")
def product_matrix(product_uuid: str, db: Session = Depends(get_db)):
    """
    Returns unique runsizes + colorspecs from the BASE PRICE MATRIX.
    This is what the UI should use for dropdowns.
    """
    rows = db.execute(
        select(PricingBasePrice).where(PricingBasePrice.product_uuid == product_uuid)
    ).scalars().all()

    if not rows:
        return {
            "product_uuid": product_uuid,
            "runsizes": [],
            "colorspecs": [],
            "count_prices": 0,
            "note": "No baseprices found. Import baseprices for this product first.",
        }

    runsizes = {}
    colorspecs = {}

    for r in rows:
        if r.runsize_uuid:
            runsizes[str(r.runsize_uuid)] = r.runsize or str(r.runsize_uuid)
        if r.colorspec_uuid:
            colorspecs[str(r.colorspec_uuid)] = r.colorspec or str(r.colorspec_uuid)

    return {
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": k, "runsize": v} for k, v in runsizes.items()],
        "colorspecs": [{"colorspec_uuid": k, "colorspec": v} for k, v in colorspecs.items()],
        "count_prices": len(rows),
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
        "product_uuid": product_uuid,
        "runsize_uuid": runsize_uuid,
        "colorspec_uuid": colorspec_uuid,
        "base_price": float(row.product_baseprice) if row.product_baseprice is not None else None,
        "runsize": row.runsize,
        "colorspec": row.colorspec,
    }


# ---------------------------
# Minimal UI
# ---------------------------

@router.get("/tester/{product_uuid}", response_class=HTMLResponse)
def tester_ui(product_uuid: str, db: Session = Depends(get_db)):
    # Minimal HTML page to prove DB + matrix dropdown + price lookups
    return HTMLResponse(
        f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pricing Tester</title>
  <style>
    body {{ font-family: Arial; padding: 18px; max-width: 900px; margin: 0 auto; }}
    select, button {{ padding: 10px; margin: 8px 0; width: 100%; }}
    .row {{ margin-bottom: 12px; }}
    pre {{ background: #f6f6f6; padding: 12px; border-radius: 8px; overflow: auto; }}
    h1 {{ margin-top: 0; }}
    .muted {{ color: #666; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>Pricing Tester</h1>
  <div class="row"><b>Product UUID:</b> {product_uuid}</div>
  <div class="row muted">This tester loads Runsize + Colorspec from the base price matrix.</div>

  <div class="row">
    <button onclick="loadAll()">Load Config + Matrix</button>
  </div>

  <div class="row">
    <label>Runsize</label>
    <select id="runsize"></select>
  </div>

  <div class="row">
    <label>Colorspec</label>
    <select id="colorspec"></select>
  </div>

  <div class="row">
    <button onclick="price()">Get Price</button>
  </div>

  <h3>Result</h3>
  <pre id="out">Click "Load Config + Matrix"</pre>

<script>
async function loadAll() {{
  const out = document.getElementById('out');
  out.textContent = "Loading...";

  const [cres, mres] = await Promise.all([
    fetch(`/pricing/product/{product_uuid}/config`),
    fetch(`/pricing/product/{product_uuid}/matrix`)
  ]);

  const config = await cres.json();
  const matrix = await mres.json();

  const runSel = document.getElementById('runsize');
  const colSel = document.getElementById('colorspec');

  const runsizes = matrix.runsizes || [];
  const colorspecs = matrix.colorspecs || [];

  runSel.innerHTML = runsizes.map(r => `<option value="${{r.runsize_uuid}}">${{r.runsize}}</option>`).join('');
  colSel.innerHTML = colorspecs.map(c => `<option value="${{c.colorspec_uuid}}">${{c.colorspec}}</option>`).join('');

  out.textContent = JSON.stringify({{
    product: config.product,
    groups_count: (config.groups || []).length,
    matrix_count_prices: matrix.count_prices,
    runsizes: runsizes.length,
    colorspecs: colorspecs.length
  }}, null, 2);
}}

async function price() {{
  const out = document.getElementById('out');
  const run = document.getElementById('runsize').value;
  const col = document.getElementById('colorspec').value;

  if (!run || !col) {{
    out.textContent = "Pick Runsize + Colorspec first.";
    return;
  }}

  const res = await fetch(`/pricing/price?product_uuid={product_uuid}&runsize_uuid=${{encodeURIComponent(run)}}&colorspec_uuid=${{encodeURIComponent(col)}}`);
  const data = await res.json();
  out.textContent = JSON.stringify(data, null, 2);
}}
</script>
</body>
</html>
"""
    )
