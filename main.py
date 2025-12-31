import json
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from db import engine, Base, get_db
from models import RawPayload
from config import DEBUG
from four_over_client import FourOverClient, FourOverError

app = FastAPI(title="catdi-4over-connector", version="0.9")

# Create tables on startup
Base.metadata.create_all(bind=engine)

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.9", "build": "ROOT_MAIN_PY_V3", "debug": DEBUG}

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    # quick roundtrip
    db.execute(text("SELECT 1"))
    return {"ok": True}

@app.get("/4over/whoami")
def whoami(db: Session = Depends(get_db)):
    try:
        client = FourOverClient()
        data, debug = client.whoami()
        db.add(RawPayload(kind="whoami", ref_id="whoami", payload_json=json.dumps(data)))
        db.commit()
        return {"ok": True, "data": data, "debug": debug}
    except FourOverError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/categories")
def categories(db: Session = Depends(get_db)):
    try:
        client = FourOverClient()
        data, debug = client.categories()
        db.add(RawPayload(kind="categories", ref_id="all", payload_json=json.dumps(data)))
        db.commit()
        return {"ok": True, "data": data, "debug": debug}
    except FourOverError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/categories/{category_uuid}/products")
def category_products(category_uuid: str, pages: int = 1, db: Session = Depends(get_db)):
    try:
        client = FourOverClient()
        data, debug = client.category_products(category_uuid, pages=pages)
        db.add(RawPayload(kind="category_products", ref_id=category_uuid, payload_json=json.dumps(data)))
        db.commit()
        return {"ok": True, "data": data, "debug": debug}
    except FourOverError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/doorhangers/tester")
def doorhanger_tester(product_uuid: str, db: Session = Depends(get_db)):
    """
    Simple tester endpoint: fetch product details for a given product_uuid
    so we can inspect option groups / structure.
    """
    try:
        client = FourOverClient()
        data, debug = client.product_options(product_uuid)
        db.add(RawPayload(kind="product", ref_id=product_uuid, payload_json=json.dumps(data)))
        db.commit()
        return {"ok": True, "product_uuid": product_uuid, "data": data, "debug": debug}
    except FourOverError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str, db: Session = Depends(get_db)):
    """
    Import = fetch product payload and store it. (Later we’ll normalize option groups into tables.)
    """
    try:
        client = FourOverClient()
        data, debug = client.product_options(product_uuid)
        db.add(RawPayload(kind="doorhanger_import", ref_id=product_uuid, payload_json=json.dumps(data)))
        db.commit()
        return {"ok": True, "imported": product_uuid, "debug": debug}
    except FourOverError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
