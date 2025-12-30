from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Optional, Dict, Any, List
import re
from sqlalchemy.orm import Session
from sqlalchemy import text

from fourover_client import FourOverClient
from db import engine, get_db
from models import Product, OptionGroup, Option, BasePrice
from db import Base as SqlBase


APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE2_DB_CACHE"
BUILD = "PRICING_TESTER_DB_2025-12-30"

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

app = FastAPI(title=APP_NAME)

_client: Optional[FourOverClient] = None


def four_over() -> FourOverClient:
    global _client
    if _client is None:
        _client = FourOverClient()
    return _client


def _json_or_text(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": (resp.text or "")[:2000]}


@app.on_event("startup")
def startup():
    # Create tables if they don't exist (simple, no Alembic yet)
    SqlBase.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


# ---------- DB ----------
@app.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "db": "reachable"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- 4over passthrough ----------
@app.get("/4over/whoami")
def whoami():
    try:
        r, _dbg = four_over().get("/whoami", params={})
        if not r.ok:
            return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/printproducts/categories/{category_uuid}/products")
def category_products(
    category_uuid: str,
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    try:
        path = f"/printproducts/categories/{category_uuid}/products"
        r, dbg = four_over().get(path, params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)


@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
    try:
        path = f"/printproducts/products/{product_uuid}/optiongroups"
        r, dbg = four_over().get(path, params={"max": 1000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        path = f"/printproducts/products/{product_uuid}/baseprices"
        r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- SYNC to Postgres ----------
def upsert_product(db: Session, p: Dict[str, Any]) -> Product:
    product_uuid = p.get("product_uuid")
    existing = db.get(Product, product_uuid)
    if existing is None:
        existing = Product(product_uuid=product_uuid)

    existing.product_code = p.get("product_code")
    existing.product_description = p.get("product_description")
    existing.full_product_path = p.get("full_product_path")
    existing.categories_path = p.get("categories")
    existing.optiongroups_path = p.get("product_option_groups")
    existing.baseprices_path = p.get("product_base_prices")

    db.add(existing)
    return existing


def replace_optiongroups(db: Session, product_uuid: str, og_payload: Dict[str, Any]):
    # Delete existing groups/options for product and rebuild (simple + reliable)
    db.query(Option).join(OptionGroup).filter(OptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(OptionGroup).filter(OptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)

    groups = og_payload.get("entities", [])
    for g in groups:
        og = OptionGroup(
            product_uuid=product_uuid,
            group_uuid=g.get("product_option_group_uuid"),
            group_name=g.get("product_option_group_name"),
            minoccurs=str(g.get("minoccurs")) if g.get("minoccurs") is not None else None,
            maxoccurs=str(g.get("maxoccurs")) if g.get("maxoccurs") is not None else None,
        )
        db.add(og)
        db.flush()  # to get og.id

        for opt in g.get("options", []) or []:
            o = Option(
                option_group_id=og.id,
                option_uuid=opt.get("option_uuid"),
                option_name=opt.get("option_name"),
                option_description=opt.get("option_description"),
                capi_name=opt.get("capi_name"),
                capi_description=opt.get("capi_description"),
                runsize_uuid=opt.get("runsize_uuid"),
                runsize=opt.get("runsize"),
                colorspec_uuid=opt.get("colorspec_uuid"),
                colorspec=opt.get("colorspec"),
                option_prices_path=opt.get("option_prices"),
            )
            db.add(o)


def replace_baseprices(db: Session, product_uuid: str, bp_payload: Dict[str, Any]):
    # Delete existing baseprices for product and rebuild
    db.query(BasePrice).filter(BasePrice.product_uuid == product_uuid).delete(synchronize_session=False)

    rows = bp_payload.get("entities", [])
    for row in rows:
        bp = BasePrice(
            base_price_uuid=row.get("base_price_uuid"),
            product_uuid=product_uuid,
            product_baseprice=row.get("product_baseprice"),
            can_group_ship=bool(row.get("can_group_ship", False)),
            runsize_uuid=row.get("runsize_uuid"),
            runsize=row.get("runsize"),
            colorspec_uuid=row.get("colorspec_uuid"),
            colorspec=row.get("colorspec"),
        )
        db.add(bp)


@app.post("/sync/doorhangers")
def sync_doorhangers(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Pull Door Hangers products from 4over and store them (products + optiongroups + baseprices) into Postgres.
    This is the "cache warmup" step so the pricing UI stays fast.
    """
    from db import SessionLocal

    db = SessionLocal()
    try:
        listing = doorhangers_products(max=max, offset=offset)
        items = listing.get("entities", []) if isinstance(listing, dict) else []

        synced = 0
        for p in items:
            prod = upsert_product(db, p)

            # optiongroups
            og = doorhangers_optiongroups(prod.product_uuid)
            if isinstance(og, dict) and og.get("entities") is not None:
                replace_optiongroups(db, prod.product_uuid, og)

            # baseprices
            bp = doorhangers_baseprices(prod.product_uuid)
            if isinstance(bp, dict) and bp.get("entities") is not None:
                replace_baseprices(db, prod.product_uuid, bp)

            synced += 1

        db.commit()
        return {"ok": True, "synced_products": synced}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ---------- Pricing Tester APIs (DB-backed, fast) ----------
@app.get("/catalog/doorhangers")
def catalog_doorhangers():
    """
    Returns all door hanger products in DB.
    """
    from db import SessionLocal
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.product_code.asc()).all()
        return {
            "count": len(products),
            "items": [
                {
                    "product_uuid": p.product_uuid,
                    "product_code": p.product_code,
                    "product_description": p.product_description,
                }
                for p in products
            ],
        }
    finally:
        db.close()


@app.get("/catalog/doorhangers/{product_uuid}/options")
def catalog_doorhangers_options(product_uuid: str):
    """
    Returns dropdown groups/options for a product from DB.
    """
    from db import SessionLocal
    db = SessionLocal()
    try:
        groups = (
            db.query(OptionGroup)
            .filter(OptionGroup.product_uuid == product_uuid)
            .order_by(OptionGroup.group_name.asc())
            .all()
        )

        out = []
        for g in groups:
            opts = db.query(Option).filter(Option.option_group_id == g.id).order_by(Option.option_name.asc()).all()
            out.append(
                {
                    "group_uuid": g.group_uuid,
                    "group_name": g.group_name,
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
                        for o in opts
                    ],
                }
            )

        return {"product_uuid": product_uuid, "groups": out}
    finally:
        db.close()


@app.get("/price/doorhangers")
def price_doorhangers(
    product_uuid: str = Query(...),
    runsize_uuid: str = Query(...),
    colorspec_uuid: str = Query(...),
):
    """
    DB lookup: base price by product + runsize + colorspec.
    (Later we add turnaround + add-ons pricing.)
    """
    from db import SessionLocal
    db = SessionLocal()
    try:
        row = (
            db.query(BasePrice)
            .filter(
                BasePrice.product_uuid == product_uuid,
                BasePrice.runsize_uuid == runsize_uuid,
                BasePrice.colorspec_uuid == colorspec_uuid,
            )
            .first()
        )
        if not row:
            return {"ok": False, "message": "No base price found for that combination."}

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsize_uuid": runsize_uuid,
            "colorspec_uuid": colorspec_uuid,
            "base_price": float(row.product_baseprice),
        }
    finally:
        db.close()


# ---------- Simple HTML Pricing Tester (fast & easy) ----------
@app.get("/tester/doorhangers", response_class=HTMLResponse)
def tester_doorhangers():
    """
    Simple HTML tester page (no frontend build tools).
    """
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Door Hangers Pricing Tester</title>
  <style>
    body{font-family:Arial; max-width:900px; margin:40px auto; padding:0 16px;}
    .row{display:flex; gap:12px; margin:12px 0; flex-wrap:wrap;}
    select, button{padding:10px; font-size:14px;}
    .card{border:1px solid #ddd; padding:16px; border-radius:10px;}
    .price{font-size:26px; font-weight:bold; margin-top:12px;}
    small{color:#666;}
  </style>
</head>
<body>
  <h1>Door Hangers Pricing Tester</h1>
  <div class="card">
    <div class="row">
      <div>
        <div><small>Product</small></div>
        <select id="product"></select>
      </div>
      <div>
        <div><small>Run Size</small></div>
        <select id="runsize"></select>
      </div>
      <div>
        <div><small>Color</small></div>
        <select id="colorspec"></select>
      </div>
      <div style="display:flex;align-items:flex-end;">
        <button onclick="getPrice()">Get Price</button>
      </div>
    </div>

    <div id="desc"></div>
    <div class="price" id="price"></div>
    <div id="debug"></div>
  </div>

<script>
async function loadProducts(){
  const res = await fetch('/catalog/doorhangers');
  const data = await res.json();
  const sel = document.getElementById('product');
  sel.innerHTML = '';
  data.items.forEach(p=>{
    const opt = document.createElement('option');
    opt.value = p.product_uuid;
    opt.textContent = `${p.product_code} — ${p.product_description}`;
    sel.appendChild(opt);
  });
  sel.onchange = loadOptions;
  await loadOptions();
}

async function loadOptions(){
  const product_uuid = document.getElementById('product').value;
  document.getElementById('price').textContent = '';
  document.getElementById('debug').textContent = '';

  const res = await fetch(`/catalog/doorhangers/${product_uuid}/options`);
  const data = await res.json();

  // We only need groups that contain runsize/colorspec choices.
  // In your data, Runsize group = "Runsize", Colorspec group = "Colorspec"
  const runGroup = data.groups.find(g => g.group_name.toLowerCase() === 'runsize');
  const colGroup = data.groups.find(g => g.group_name.toLowerCase() === 'colorspec');

  const runSel = document.getElementById('runsize');
  const colSel = document.getElementById('colorspec');

  runSel.innerHTML = '';
  colSel.innerHTML = '';

  if(runGroup){
    runGroup.options.forEach(o=>{
      const opt = document.createElement('option');
      opt.value = o.option_uuid;
      opt.textContent = o.option_name;
      runSel.appendChild(opt);
    });
  }

  if(colGroup){
    colGroup.options.forEach(o=>{
      const opt = document.createElement('option');
      opt.value = o.option_uuid;
      opt.textContent = o.option_name;
      colSel.appendChild(opt);
    });
  }

  // show description-ish
  const prodText = document.getElementById('product').selectedOptions[0]?.textContent || '';
  document.getElementById('desc').textContent = prodText;
}

async function getPrice(){
  const product_uuid = document.getElementById('product').value;
  const runsize_uuid = document.getElementById('runsize').value;
  const colorspec_uuid = document.getElementById('colorspec').value;

  const url = `/price/doorhangers?product_uuid=${encodeURIComponent(product_uuid)}&runsize_uuid=${encodeURIComponent(runsize_uuid)}&colorspec_uuid=${encodeURIComponent(colorspec_uuid)}`;
  const res = await fetch(url);
  const data = await res.json();

  if(!data.ok){
    document.getElementById('price').textContent = 'No price found';
    document.getElementById('debug').textContent = JSON.stringify(data);
    return;
  }
  document.getElementById('price').textContent = `$${data.base_price.toFixed(2)}`;
  document.getElementById('debug').textContent = '';
}

loadProducts();
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)
