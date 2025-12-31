# pricing_tester.py
from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    rows = db.execute(select(PricingProduct)).scalars().all()
    return [
        {"product_uuid": r.product_uuid, "product_code": r.product_code, "product_description": r.product_description}
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

        out_groups.append({
            "group_uuid": g.product_option_group_uuid,
            "name": g.name,
            "minoccurs": g.minoccurs,
            "maxoccurs": g.maxoccurs,
            "options": [{
                "option_uuid": o.option_uuid,
                "option_name": o.option_name,
                "option_description": o.option_description,
            } for o in options]
        })

    return {
        "product": {
            "product_uuid": p.product_uuid,
            "product_code": p.product_code,
            "product_description": p.product_description,
        },
        "groups": out_groups
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
        "base_price": float(row.product_baseprice),
        "runsize": row.runsize,
        "colorspec": row.colorspec,
    }


@router.get("/tester/{product_uuid}", response_class=HTMLResponse)
def tester_ui(product_uuid: str, db: Session = Depends(get_db)):
    p = db.get(PricingProduct, product_uuid)
    if not p:
        return HTMLResponse(f"<h2>Product not found in DB.</h2><p>Run POST /doorhangers/import/{product_uuid} first.</p>", status_code=404)

    return HTMLResponse(f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pricing Tester</title>
  <style>
    body {{ font-family: Arial; padding: 18px; max-width: 900px; margin: 0 auto; }}
    select, button {{ padding: 8px; margin: 6px 0; width: 100%; }}
    .row {{ margin-bottom: 12px; }}
    pre {{ background: #f6f6f6; padding: 12px; border-radius: 8px; overflow: auto; }}
    h1 {{ margin-top: 0; }}
    .muted {{ color: #666; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>Pricing Tester</h1>
  <div class="row"><b>{p.product_code}</b><div class="muted">{p.product_description}</div></div>
  <div class="row"><b>Product UUID:</b> {product_uuid}</div>

  <div class="row">
    <button onclick="loadAll()">Load Dropdowns</button>
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
  <pre id="out">Click "Load Dropdowns"</pre>

<script>
async function loadAll() {{
  const keysRes = await fetch(`/doorhangers/matrix_keys?product_uuid={product_uuid}`);
  const keys = await keysRes.json();

  if (!keys.ok) {{
    document.getElementById('out').textContent = JSON.stringify(keys, null, 2);
    return;
  }}

  const runSel = document.getElementById('runsize');
  const colSel = document.getElementById('colorspec');

  runSel.innerHTML = (keys.runsizes || []).map(r =>
    `<option value="${{r.runsize_uuid}}">${{r.runsize || r.runsize_uuid}}</option>`
  ).join('');

  colSel.innerHTML = (keys.colorspecs || []).map(c =>
    `<option value="${{c.colorspec_uuid}}">${{c.colorspec || c.colorspec_uuid}}</option>`
  ).join('');

  document.getElementById('out').textContent = JSON.stringify(keys, null, 2);
}}

async function price() {{
  const run = document.getElementById('runsize').value;
  const col = document.getElementById('colorspec').value;

  const res = await fetch(`/pricing/price?product_uuid={product_uuid}&runsize_uuid=${{encodeURIComponent(run)}}&colorspec_uuid=${{encodeURIComponent(col)}}`);
  const data = await res.json();
  document.getElementById('out').textContent = JSON.stringify(data, null, 2);
}}
</script>
</body>
</html>
    """)
