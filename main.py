import logging
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from db import Base, engine, get_db
from models import ProductFeedItem

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("catdi-4over-connector")

app = FastAPI()

@app.on_event("startup")
def startup():
    try:
        Base.metadata.create_all(bind=engine)
        log.info("DB tables ensured")
    except Exception as e:
        log.exception("DB init failed (app still boots): %s", e)

@app.get("/health")
def health():
    return {"ok": True, "status": "booted"}

@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    c = db.query(ProductFeedItem).count()
    return {"ok": True, "db": "ok", "count": c}
