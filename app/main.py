from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.db import Base, engine, SessionLocal
from app.models import Category, Product, OptionGroup, Option
from app.config import FOUR_OVER_BASE_URL, FOUR_OVER_API_PREFIX, FOUR_OVER_TIMEOUT
from app.fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector")

# --- Startup: create tables ---
Base.metadata.create_all(bind=engine)

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "db": "up"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/auth")
def debug_auth():
    return {
        "FOUR_OVER_BASE_URL": FOUR_OVER_BASE_URL,
        "FOUR_OVER_API_PREFIX": FOUR_OVER_API_PREFIX,
        "FOUR_OVER_TIMEOUT": str(FOUR_OVER_TIMEOUT),
        "FOUR_OVER_APIKEY_present": True,
        "FOUR_OVER_PRIVATE_KEY_present": True,
    }

# ----------------------------
# 4OVER PROXY ENDPOINTS
# ----------------------------

@app.get("/4over/whoami")
def whoami():
    client = FourOverClient()
    status, url, canonical, r = client.get("/whoami", use_prefix=False)
    if status != 200:
        return {"ok": False, "http_code": status, "data": r.json() if r.content else None, "debug": {"url": url, "canonical": canonical}}
    return {"ok": True, "data": r.json()}

@app.get("/4over/categories")
def categories(max: int = 50, offset: int = 0):
    client = FourOverClient()
    status, url, canonical, r = client.get("/categories", params={"max": max, "offset": offset}, use_prefix=True)
    if status != 200:
        return {"ok": False, "http_code": status, "data": r.json() if r.content else None, "debug": {"url": url, "canonical": canonical}}
    return {"ok": True, "data": r.json()}

@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    client = FourOverClient()
    status, url, canonical, r = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset}, use_prefix=True)
    if status != 200:
        return {"ok": False, "http_code": status, "data": r.json() if r.content else None, "debug": {"url": url, "canonical": canonical}}
    return {"ok": True, "data": r.json()}

@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    client = FourOverClient()
    status, url, canonical, r = client.get(f"/products/{product_uuid}", use_prefix=True)
    if status != 200:
        return {"ok": False, "http_code": status, "data": r.json() if r.content else None, "debug": {"url": url, "canonical": canonical}}
    return {"ok": True, "data": r.json()}

# ----------------------------
# SYNC INTO DB (SCALABLE)
# ----------------------------

@app.post("/sync/products/{product_uuid}")
def sync_product(product_uuid: str):
    client = FourOverClient()

    status, url, canonical, r = client.get(f"/products/{product_uuid}", use_prefix=True)
    if status != 200:
        raise HTTPException(status_code=500, detail={"ok": False, "http_code": status, "url": url, "canonical": canonical, "response": r.json() if r.content else None})

    payload = r.json()

    db = SessionLocal()
    try:
        # Category (first one)
        cat_uuid = None
        if payload.get("categories"):
            c0 = payload["categories"][0]
            cat_uuid = c0.get("category_uuid")
            if cat_uuid:
                cat = db.get(Category, cat_uuid)
                if not cat:
                    cat = Category(
                        category_uuid=cat_uuid,
                        category_name=c0.get("category_name") or "",
                        category_description=c0.get("category_description"),
                    )
                    db.add(cat)
                else:
                    cat.category_name = c0.get("category_name") or cat.category_name
                    cat.category_description = c0.get("category_description") or cat.category_description

        # Product
        prod = db.get(Product, product_uuid)
        if not prod:
            prod = Product(
                product_uuid=product_uuid,
                product_code=payload.get("product_code"),
                product_description=payload.get("product_description"),
                category_uuid=cat_uuid,
            )
            db.add(prod)
        else:
            prod.product_code = payload.get("product_code") or prod.product_code
            prod.product_description = payload.get("product_description") or prod.product_description
            prod.category_uuid = cat_uuid or prod.category_uuid

        db.flush()

        # Clear old option groups/options for clean re-sync
        db.query(Option).filter(
            Option.group_uuid.in_(
                db.query(OptionGroup.product_option_group_uuid).filter(OptionGroup.product_uuid == product_uuid)
            )
        ).delete(synchronize_session=False)
        db.query(OptionGroup).filter(OptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
        db.flush()

        # Insert option groups + options
        for g in payload.get("product_option_groups", []):
            g_uuid = g.get("product_option_group_uuid")
            og = OptionGroup(
                product_option_group_uuid=g_uuid,
                product_uuid=product_uuid,
                name=g.get("product_option_group_name"),
                minoccurs=str(g.get("minoccurs")) if g.get("minoccurs") is not None else None,
                maxoccurs=str(g.get("maxoccurs")) if g.get("maxoccurs") is not None else None,
            )
            db.add(og)
            db.flush()

            for opt in g.get("options", []):
                o = Option(
                    option_uuid=opt.get("option_uuid"),
                    group_uuid=g_uuid,
                    option_name=opt.get("option_name"),
                    option_description=opt.get("option_description"),
                    prices_url=opt.get("option_prices"),
                )
                db.add(o)

        db.commit()

        return {
            "ok": True,
            "synced": {
                "product_uuid": product_uuid,
                "product_code": payload.get("product_code"),
                "groups": len(payload.get("product_option_groups", [])),
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
