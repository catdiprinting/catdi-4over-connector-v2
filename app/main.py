from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from app.db import get_db, init_db
from app.fourover_client import FourOverClient
from app import models

app = FastAPI(title="catdi-4over-connector", version="1.0")

client = FourOverClient()


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        return {"ok": True, "db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/auth")
def debug_auth():
    # don't leak secrets; just confirm presence
    from app.config import FOUR_OVER_BASE_URL, FOUR_OVER_API_PREFIX, FOUR_OVER_TIMEOUT, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY
    return {
        "FOUR_OVER_BASE_URL": FOUR_OVER_BASE_URL,
        "FOUR_OVER_API_PREFIX": FOUR_OVER_API_PREFIX,
        "FOUR_OVER_APIKEY_present": bool(FOUR_OVER_APIKEY),
        "FOUR_OVER_PRIVATE_KEY_present": bool(FOUR_OVER_PRIVATE_KEY),
        "FOUR_OVER_TIMEOUT": str(FOUR_OVER_TIMEOUT),
    }


# ----------------------------
# 4over passthrough endpoints
# ----------------------------

@app.get("/4over/whoami")
def whoami():
    r = client.get("/whoami")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories")
def categories(max: int = 50, offset: int = 0):
    r = client.get("/categories", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    r = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    r = client.get(f"/products/{product_uuid}")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = 200, offset: int = 0):
    r = client.get(f"/products/{product_uuid}/baseprices", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


# ----------------------------
# Sync into DB (scalable)
# ----------------------------

@app.post("/sync/categories")
def sync_categories(pages: int = 1, page_size: int = 200, db: Session = Depends(get_db)):
    """
    Pull categories and upsert into DB.
    """
    offset = 0
    total = 0
    for _ in range(pages):
        r = client.get("/categories", params={"max": page_size, "offset": offset})
        if not r.ok:
            raise HTTPException(status_code=502, detail={"ok": False, "http_code": r.status_code, "response": r.json() if r.text else r.text})

        payload = r.json()
        entities = payload.get("entities") or payload.get("data", {}).get("entities") or []
        if not entities:
            break

        for c in entities:
            cu = c.get("category_uuid")
            if not cu:
                continue
            obj = db.get(models.Category, cu) or models.Category(category_uuid=cu)
            obj.category_name = c.get("category_name") or ""
            obj.category_description = c.get("category_description")
            db.add(obj)
            total += 1

        db.commit()
        offset += page_size

    return {"ok": True, "synced": total}


@app.post("/sync/products/{product_uuid}")
def sync_product(product_uuid: str, db: Session = Depends(get_db)):
    """
    Pull ONE product details + option groups + base prices and store.
    """
    # 1) details
    r = client.get(f"/products/{product_uuid}")
    if not r.ok:
        raise HTTPException(status_code=502, detail={"ok": False, "http_code": r.status_code, "response": r.json() if r.text else r.text})
    detail = r.json()

    # product core
    prod = db.get(models.Product, product_uuid) or models.Product(product_uuid=product_uuid)
    prod.product_code = detail.get("product_code") or ""
    prod.product_description = detail.get("product_description")

    # category (first one)
    cats = detail.get("categories") or []
    if cats:
        cu = cats[0].get("category_uuid")
        if cu:
            cat = db.get(models.Category, cu) or models.Category(category_uuid=cu, category_name=cats[0].get("category_name") or cu)
            db.add(cat)
            prod.category_uuid = cu

    db.add(prod)
    db.commit()

    # 2) option groups
    # wipe existing groups/options for clean replace
    db.query(models.OptionGroup).filter(models.OptionGroup.product_uuid == product_uuid).delete()
    db.commit()

    for g in detail.get("product_option_groups") or []:
        og = models.OptionGroup(
            product_uuid=product_uuid,
            group_uuid=g.get("product_option_group_uuid") or "",
            group_name=g.get("product_option_group_name"),
            minoccurs=str(g.get("minoccurs")) if g.get("minoccurs") is not None else None,
            maxoccurs=str(g.get("maxoccurs")) if g.get("maxoccurs") is not None else None,
        )
        db.add(og)
        db.flush()  # gives og.id

        for opt in g.get("options") or []:
            o = models.Option(
                group_id=og.id,
                option_uuid=opt.get("option_uuid") or "",
                option_name=opt.get("option_name"),
                option_description=opt.get("option_description"),
            )
            db.add(o)

    db.commit()

    # 3) base prices (store raw rows; we can normalize later)
    db.query(models.BasePrice).filter(models.BasePrice.product_uuid == product_uuid).delete()
    db.commit()

    rp = client.get(f"/products/{product_uuid}/baseprices", params={"max": 500, "offset": 0})
    if rp.ok:
        prices_payload = rp.json()
        # Store whole payload so nothing is lost
        bp = models.BasePrice(product_uuid=product_uuid, raw_json=json.dumps(prices_payload))
        db.add(bp)
        db.commit()

    return {"ok": True, "product_uuid": product_uuid, "stored": {"product": True, "option_groups": True, "base_prices": rp.ok}}
