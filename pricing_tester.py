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


@router.post("/import/{product_uuid}")
def import_pricing_bundle(product_uuid: str, payload: dict, db: Session = Depends(get_db)):
    """
    Import a full pricing bundle for ONE product.
    Payload format (what you already have):
      {
        "product": {... from products/entities ...},
        "optiongroups": {... full optiongroups response ...},
        "baseprices": {... full baseprices response ...}
      }
    """
    product = payload.get("product")
    optiongroups = payload.get("optiongroups")
    baseprices = payload.get("baseprices")

    if not product or not optiongroups or not baseprices:
        raise HTTPException(status_code=400, detail="Payload must include: product, optiongroups, baseprices")

    if product.get("product_uuid") != product_uuid:
        raise HTTPException(status_code=400, detail="product_uuid in URL does not match payload.product.product_uuid")

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

    # Clear old option groups/options + base prices for clean re-import
    # (safe because it’s per-product)
    db.query(PricingOption).filter(
        PricingOption.group_uuid.in_(
            db.query(PricingOptionGroup.product_option_group_uuid)
            .filter(PricingOptionGroup.product_uuid == product_uuid)
        )
    ).delete(synchronize_session=False)

    db.query(PricingOptionGroup).filter(PricingOptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(PricingBasePrice).filter(PricingBasePrice.product_uuid == product_uuid).delete(synchronize_session=False)

    # Insert option groups + options
    for g in optiongroups.get("entities", []):
        group_uuid = g.get("product_option_group_uuid")
        grp = PricingOptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            name=g.get("product_option_group_name") or "",
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)

        for opt in g.get("options", []) or []:
            db.add(PricingOption(
                option_uuid=opt.get("option_uuid"),
                group_uuid=group_uuid,
                option_name=opt.get("option_name") or "",
                option_description=opt.get("option_description"),
                capi_name=opt.get("capi_name"),
                capi_description=opt.get("capi_description"),
                runsize_uuid=opt.get("runsize_uuid"),
                runsize=opt.get("runsize"),
                colorspec_uuid=opt.get("colorspec_uuid"),
                colorspec=opt.get("colorspec"),
            ))

    # Insert base prices (matrix)
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
    return {"ok": True, "product_uuid": product_uuid, "groups": len(optiongroups.get("entities", [])), "prices": len(baseprices.get("entities", []))}


@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    rows = db.execute(select(PricingProduct)).scalars().all()
    return [{"product_uuid": r.product_uuid, "product_code": r.product_code, "product_description": r.product_description} for r in rows]


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
                "runsize_uuid": o.runsize_uuid,
                "runsize": o.runsize,
                "colorspec_uuid": o.colorspec_uuid,
                "colorspec": o.colorspec,
            } for o in options]
        })

    return {
        "product": {"product_uuid": p.product_uuid, "product_code": p.product_code, "product_description": p.product_description},
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
    # Minimal HTML page to prove your DB + price lookups
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
  </style>
</head>
<body>
  <h1>Pricing Tester</h1>
  <div class="row"><b>Product UUID:</b> {product_uuid}</div>

  <div class="row">
    <button onclick="loadConfig()">Load Config</button>
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
  <pre id="out">Click "Load Config"</pre>

<script>
let config = null;

function uniqBy(arr, keyFn) {{
  const m = new Map();
  for (const x of arr) {{
    const k = keyFn(x);
    if (!m.has(k)) m.set(k, x);
  }}
  return Array.from(m.values());
}}

async function loadConfig() {{
  const res = await fetch(`/pricing/product/{product_uuid}/config`);
  config = await res.json();

  // Pull runsizes + colorspecs from base price matrix indirectly isn't in config;
  // so we’ll just fetch by calling /pricing/product/{product_uuid}/config and derive from Turnaround options if present.
  // Better: you can add a /pricing/product/{product_uuid}/matrix endpoint later (we will).
  const groups = config.groups || [];
  const ta = groups.find(g => (g.name || '').toLowerCase().includes('turn'));
  let runsizes = [];
  let colorspecs = [];

  if (ta && ta.options) {{
    runsizes = uniqBy(ta.options.filter(o => o.runsize_uuid), o => o.runsize_uuid);
    colorspecs = uniqBy(ta.options.filter(o => o.colorspec_uuid), o => o.colorspec_uuid);
  }}

  const runSel = document.getElementById('runsize');
  const colSel = document.getElementById('colorspec');

  runSel.innerHTML = runsizes.map(r => `<option value="${{r.runsize_uuid}}">${{r.runsize || r.option_name}}</option>`).join('');
  colSel.innerHTML = colorspecs.map(c => `<option value="${{c.colorspec_uuid}}">${{c.colorspec || c.option_name}}</option>`).join('');

  document.getElementById('out').textContent = JSON.stringify(config.product, null, 2);
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


def _to_int(v):
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_decimal(v):
    # store numeric precisely, accept string numbers from 4over
    if v is None:
        return "0"
    return str(v)
