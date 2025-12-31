# main.py
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from db import engine, Base, get_db
from config import SERVICE_NAME, APP_PHASE, APP_BUILD
from fourover import FourOverClient
from models import Category, Product

app = FastAPI(title=SERVICE_NAME)

# Create tables on startup (simple + OK for now)
Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "phase": APP_PHASE, "build": APP_BUILD}

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute("SELECT 1")
    return {"ok": True}

@app.get("/4over/whoami")
def four_over_whoami():
    client = FourOverClient()
    r = client.whoami()
    return {
        "ok": r.ok,
        "http_code": r.status_code,
        "response": safe_json(r)
    }

@app.get("/catalog/categories")
def catalog_categories(db: Session = Depends(get_db)):
    client = FourOverClient()
    r = client.categories()
    data = safe_json(r)

    if not r.ok:
        return {"ok": False, "http_code": r.status_code, "response": data}

    entities = data.get("entities") or []
    saved = 0
    for c in entities:
        cuuid = c.get("category_uuid")
        name = c.get("category_name") or ""
        desc = c.get("category_description")
        if not cuuid or not name:
            continue

        existing = db.query(Category).filter(Category.category_uuid == cuuid).first()
        if not existing:
            db.add(Category(category_uuid=cuuid, category_name=name, category_description=desc))
            saved += 1

    db.commit()
    return {"ok": True, "count": len(entities), "saved": saved}

def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}
