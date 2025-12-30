from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, distinct

from db import get_db
from models import PricingProduct, PricingOptionGroup, PricingOptionValue, PricingBasePrice
from fourover_client import FourOverClient

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


@router.get("/products")
def list_doorhangers_products(max: int = 25, offset: int = 0):
    """
    Simple passthrough list, then filter by 'Door Hangers' keyword.
    You already have product UUIDs so this is enough for now.
    """
    client = FourOverClient()
    data = client.get("/printproducts/products", params={"max": max, "offset": offset})
    entities = data.get("entities", []) or []
    filtered = [p for p in entities if "door hanger" in (p.get("product_description", "") or "").lower()]
    return {"entities": filtered, "count": len(filtered)}


@router.post("/import/{product_uuid}")
def import_product_bundle(product_uuid: str, db: Session = Depends(get_db)):
    """
    Fetch optiongroups + baseprices from 4over and store in DB.
    Uses documentation endpoints:
      /printproducts/products/{uuid}/optiongroups
      /printproducts/products/{uuid}/baseprices
    """
    client = FourOverClient()

    # Get product record (best-effort: use productsfeed if you want later)
    # For now, we just store uuid and let code/description be empty if not found.
    product_code = None
    product_description = None

    # Optiongroups + baseprices
    og = client.get(f"/printproducts/products/{product_uuid}/optiongroups")
    bp = client.get(f"/printproducts/products/{product_uuid}/baseprices")

    # Upsert product
    p = db.get(PricingProduct, product_uuid)
    if not p:
        p = PricingProduct(product_uuid=product_uuid, product_code=product_code, product_description=product_description)
        db.add(p)

    # Clear old per-product rows
    db.execute(delete(PricingBasePrice).where(PricingBasePrice.product_uuid == product_uuid))
    db.execute(
        delete(PricingOptionValue).where(
            PricingOptionValue.group_uuid.in_(
                select(PricingOptionGroup.product_option_group_uuid).where(PricingOptionGroup.product_uuid == product_uuid)
            )
        )
    )
    db.execute(delete(PricingOptionGroup).where(PricingOptionGroup.product_uuid == product_uuid))

    # Insert option groups + values
    for g in og.get("entities", []) or []:
        group_uuid = g.get("product_option_group_uuid")
        grp = PricingOptionGroup(
            product_option_group_uuid=group_uuid,
            product_uuid=product_uuid,
            name=g.get("product_option_group_name") or "",
            minoccurs=_to_int(g.get("minoccurs")),
            maxoccurs=_to_int(g.get("maxoccurs")),
        )
        db.add(grp)

        for v in g.get("options", []) or []:
            # 4over calls these "options" in optiongroups response.
            # We store them as "values" for UI convenience.
            db.add(
                PricingOptionValue(
                    product_option_value_uuid=v.get("option_uuid"),
                    group_uuid=group_uuid,
                    name=v.get("option_name") or "",
                    code=v.get("capi_name") or v.get("option_name"),
                    sort=None,
                )
            )

    # Insert base prices (matrix)
    inserted = 0
    for row in bp.get("entities", []) or []:
        db.add(
            PricingBasePrice(
                base_price_uuid=row.get("base_price_uuid"),
                product_uuid=product_uuid,
                product_baseprice=_to_decimal(row.get("product_baseprice")),
                runsize_uuid=row.get("runsize_uuid"),
                runsize=row.get("runsize"),
                colorspec_uuid=row.get("colorspec_uuid"),
                colorspec=row.get("colorspec"),
                can_group_ship=bool(row.get("can_group_ship", False)),
            )
        )
        inserted += 1

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "option_groups": len(og.get("entities", []) or []),
        "baseprices": inserted,
    }


@router.get("/product/{product_uuid}/baseprices")
def get_baseprices(product_uuid: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(PricingBasePrice).where(PricingBasePrice.product_uuid == product_uuid)
    ).scalars().all()

    return {
        "entities": [
            {
                "base_price_uuid": r.base_price_uuid,
                "product_baseprice": str(r.product_baseprice),
                "runsize_uuid": r.runsize_uuid,
                "runsize": r.runsize,
                "colorspec_uuid": r.colorspec_uuid,
                "colorspec": r.colorspec,
                "product_uuid": r.product_uuid,
                "can_group_ship": bool(r.can_group_ship),
            }
            for r in rows
        ]
    }


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    # Derive keys from BASEPRICES (not optiongroups). This is the important fix.
    runs = db.execute(
        select(distinct(PricingBasePrice.runsize_uuid), PricingBasePrice.runsize)
        .where(PricingBasePrice.product_uuid == product_uuid)
        .where(PricingBasePrice.runsize_uuid.is_not(None))
        .order_by(PricingBasePrice.runsize)
    ).all()

    cols = db.execute(
        select(distinct(PricingBasePrice.colorspec_uuid), PricingBasePrice.colorspec)
        .where(PricingBasePrice.product_uuid == product_uuid)
        .where(PricingBasePrice.colorspec_uuid.is_not(None))
        .order_by(PricingBasePrice.colorspec)
    ).all()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsizes": [{"runsize_uuid": r[0], "runsize": r[1]} for r in runs if r[0]],
        "colorspecs": [{"colorspec_uuid": c[0], "colorspec": c[1]} for c in cols if c[0]],
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


@router.get("/tester", response_class=HTMLResponse)
def tester_ui(product_uuid: str, db: Session = Depends(get_db)):
    # DB is injected correctly (Depends) so FastAPI won't crash
    return HTMLResponse(f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>DoorHangers Pricing Tester</title>
  <style>
    body {{ font-family: Arial; padding: 18px; max-width: 900px; margin: 0 auto; }}
    select, button, input {{ padding: 10px; margin: 6px 0; width: 100%; }}
    pre {{ background: #f6f6f6; padding: 12px; border-radius: 8px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>DoorHangers Pricing Tester</h1>
  <div><b>Product UUID</b></div>
  <input id="pu" value="{product_uuid}" />

  <button onclick="loadKeys()">Load Matrix Keys</button>

  <label>Runsize</label>
  <select id="run"></select>

  <label>Colorspec</label>
  <select id="col"></select>

  <button onclick="price()">Get Price</button>

  <h3>Result</h3>
  <pre id="out">Click "Load Matrix Keys"</pre>

<script>
async function loadKeys() {{
  const pu = document.getElementById('pu').value.trim();
  const res = await fetch(`/doorhangers/matrix_keys?product_uuid=${{encodeURIComponent(pu)}}`);
  const data = await res.json();

  document.getElementById('run').innerHTML =
    (data.runsizes || []).map(r => `<option value="${{r.runsize_uuid}}">${{r.runsize}}</option>`).join('');

  document.getElementById('col').innerHTML =
    (data.colorspecs || []).map(c => `<option value="${{c.colorspec_uuid}}">${{c.colorspec}}</option>`).join('');

  document.getElementById('out').textContent = JSON.stringify(data, null, 2);
}}

async function price() {{
  const pu = document.getElementById('pu').value.trim();
  const run = document.getElementById('run').value;
  const col = document.getElementById('col').value;

  const res = await fetch(`/doorhangers/price?product_uuid=${{encodeURIComponent(pu)}}&runsize_uuid=${{encodeURIComponent(run)}}&colorspec_uuid=${{encodeURIComponent(col)}}`);
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
    if v is None:
        return "0"
    return str(v)
