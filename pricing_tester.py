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

def _to_int(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None

def _to_decimal_str(v):
    # accept 4over numeric strings
    if v is None or v == "":
        return "0"
    return str(v)

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
        raise HTTPException(status_code=400, detail="Payload must include: product, optiongroups, baseprices")

    if str(product.get("product_uuid")) != str(product_uuid):
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

    # Delete per-product (safe, avoids joins causing delete() errors)
    group_uuids = db.execute(
        select(PricingOptionGroup.product_option_group_uuid).where(PricingOptionGroup.product_uuid == product_uuid)
    ).scalars().all()

    if group_uuids:
        db.query(PricingOption).filter(PricingOption.group_uuid.in_(group_uuids)).delete(synchronize_session=False)

    db.query(PricingOptionGroup).filter(PricingOptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(PricingBasePrice).filter(PricingBasePrice.product_uuid == product_uuid).delete(synchronize_session=False)

    # Insert option groups + options
    for g in optiongroups.get("entities", []):
        group_uuid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
        if not group_uuid:
            continue

        grp = PricingOptionGroup(
            product_option_group_uuid=str(group_uuid),
            product_uuid=product_uuid,
            name=g.get("name") or g.get("product_option_group_name"),
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)

        values = g.get("values") or g.get("options") or []
        for opt in values:
            opt_uuid = opt.get("product_option_value_uuid") or opt.get("option_uuid") or opt.get("uuid")
            if not opt_uuid:
                continue

            db.add(PricingOption(
                option_uuid=str(opt_uuid),
                group_uuid=str(group_uuid),
                option_name=opt.get("name") or opt.get("option_name"),
                option_description=opt.get("option_description") or opt.get("description"),
                capi_name=opt.get("capi_name"),
                capi_description=opt.get("capi_description"),
                runsize_uuid=opt.get("runsize_uuid"),
                runsize=opt.get("runsize"),
                colorspec_uuid=opt.get("colorspec_uuid"),
                colorspec=opt.get("colorspec"),
            ))

    # Insert base prices (matrix)
    for bp in baseprices.get("entities", []):
        base_price_uuid = bp.get("base_price_uuid") or bp.get("product_baseprice_uuid") or bp.get("uuid")
        if not base_price_uuid:
            continue

        db.add(PricingBasePrice(
            base_price_uuid=str(base_price_uuid),
            product_uuid=product_uuid,
            product_baseprice=_to_decimal_str(bp.get("product_baseprice") or bp.get("price")),
            runsize_uuid=bp.get("runsize_uuid"),
            runsize=str(bp.get("runsize")) if bp.get("runsize") is not None else None,
            colorspec_uuid=bp.get("colorspec_uuid"),
            colorspec=str(bp.get("colorspec")) if bp.get("colorspec") is not None else None,
            can_group_ship=bool(bp.get("can_group_ship", False)),
        ))

    db.commit()
    return {
        "ok": True,
        "product_uuid": product_uuid,
        "groups": len(optiongroups.get("entities", [])),
        "prices": len(baseprices.get("entities", [])),
    }

@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    rows = db.execute(select(PricingProduct)).scalars().all()
    return [{"product_uuid": r.product_uuid, "product_code": r.product_code, "product_description": r.product_description} for r in rows]

@router.get("/product/{product_uuid}/config")
def product_config(product_uuid: str, db: Session = Depends(get_db)):
    p = db.get(PricingProduct, product_uuid)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    groups = db.execute(select(PricingOptionGroup).where(PricingOptionGroup.product_uuid == product_uuid)).scalars().all()

    out_groups = []
    for g in groups:
        options = db.execute(select(PricingOption).where(PricingOption.group_uuid == g.product_option_group_uuid)).scalars().all()
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
def tester_ui(product_uuid: str):
    return HTMLResponse(f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Pricing Tester</title>
  <style>
    body {{ font-family: Arial; padding: 18px; max-width: 900px; margin: 0 auto; }}
    select, button {{ padding: 10px; margin: 6px 0; width: 100%; }}
    .row {{ margin-bottom: 12px; }}
    pre {{ background: #f6f6f6; padding: 12px; border-radius: 8px; overflow: auto; }}
    h1 {{ margin-top: 0; }}
    .note {{ color: #666; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>Pricing Tester</h1>
  <div class="row"><b>Product UUID:</b> {product_uuid}</div>
  <div class="row note">Tip: Use /doorhangers/import/{product_uuid} first to load DB from 4over.</div>

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

  // Derive runsizes/colorspecs from baseprice table by fetching a tiny helper endpoint:
  const mres = await fetch(`/doorhangers/matrix_keys?product_uuid={product_uuid}`);
  const m = await mres.json();

  const runSel = document.getElementById('runsize');
  const colSel = document.getElementById('colorspec');

  runSel.innerHTML = (m.runsizes || []).map(r => `<option value="${{r.runsize_uuid}}">${{r.runsize}}</option>`).join('');
  colSel.innerHTML = (m.colorspecs || []).map(c => `<option value="${{c.colorspec_uuid}}">${{c.colorspec}}</option>`).join('');

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
