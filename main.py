# main.py
import os
import json
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# -----------------------------
# Config
# -----------------------------
APP_NAME = "catdi-4over-connector"
PHASE = os.getenv("PHASE", "0.7")
BUILD = os.getenv("BUILD", "doorhangers-stabilize-v1")

FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

REQ_TIMEOUT = float(os.getenv("REQ_TIMEOUT", "20"))  # seconds

# -----------------------------
# DB
# -----------------------------
Base = declarative_base()

class BasePriceCache(Base):
    __tablename__ = "baseprice_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_uuid = Column(String(64), nullable=False, index=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    payload_json = Column(Text, nullable=False)  # raw JSON string

Index("idx_baseprice_cache_product_uuid", BasePriceCache.product_uuid)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# -----------------------------
# 4over signing + request helper
# -----------------------------
def _sign_canonical(canonical: str, private_key: str) -> str:
    """
    4over signature = HMAC-SHA256(private_key, canonical_path_with_query)
    canonical example: "/whoami?apikey=XXXX"
    """
    digest = hmac.new(
        private_key.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return digest

def _canonical_path(path: str, params: Dict[str, Any]) -> str:
    """
    Build canonical string: "{path}?k=v&k2=v2" with stable sorting.
    """
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None:
            continue
        items.append(f"{k}={v}")
    qs = "&".join(items)
    return f"{path}?{qs}" if qs else path

def four_over_request(method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

    params = dict(params or {})
    params["apikey"] = FOUR_OVER_APIKEY

    canonical = _canonical_path(path, params)
    signature = _sign_canonical(canonical, FOUR_OVER_PRIVATE_KEY)

    # Per 4over pattern: signature passed as query param
    params["signature"] = signature

    url = f"{FOUR_OVER_BASE_URL}{path}"
    try:
        r = requests.request(method.upper(), url, params=params, timeout=REQ_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"4over request failed: {e}")

    if r.status_code >= 400:
        # return useful info for debugging (without leaking private key)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "4over_http_error",
                "status_code": r.status_code,
                "url": str(r.url),
                "body": (r.text[:2000] if r.text else ""),
            },
        )

    try:
        return r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"4over returned non-JSON: {r.text[:500]}")

# -----------------------------
# App
# -----------------------------
app = FastAPI(title=APP_NAME, version=PHASE)

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}

@app.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")

@app.post("/db/init")
def db_init():
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True, "tables": ["baseprice_cache"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"db init error: {e}")

# -----------------------------
# 4over sanity endpoints
# -----------------------------
@app.get("/4over/whoami")
def whoami():
    return four_over_request("GET", "/whoami")

@app.get("/4over/categories")
def categories():
    # docs: GET /printproducts/categories:contentReference[oaicite:5]{index=5}
    return four_over_request("GET", "/printproducts/categories")

@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str):
    # docs: GET /printproducts/categories/{category_uuid}/products:contentReference[oaicite:6]{index=6}
    return four_over_request("GET", f"/printproducts/categories/{category_uuid}/products")

@app.get("/4over/products/{product_uuid}/baseprices")
def product_baseprices(product_uuid: str):
    # docs: GET /printproducts/products/{product_uuid}/baseprices:contentReference[oaicite:7]{index=7}
    return four_over_request("GET", f"/printproducts/products/{product_uuid}/baseprices")

@app.get("/4over/products/{product_uuid}/optiongroups")
def product_optiongroups(product_uuid: str):
    # docs: GET /printproducts/products/{product_uuid}/optiongroups:contentReference[oaicite:8]{index=8}
    return four_over_request("GET", f"/printproducts/products/{product_uuid}/optiongroups")

# -----------------------------
# Doorhangers - cache + options + quote
# -----------------------------
def _now_utc():
    return datetime.now(timezone.utc)

def _cache_set_single(product_uuid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep ONE row per product_uuid (delete old rows then insert fresh).
    This stops the duplicate-rows confusion during Path A testing.
    """
    db = SessionLocal()
    try:
        db.query(BasePriceCache).filter(BasePriceCache.product_uuid == product_uuid).delete()
        row = BasePriceCache(
            product_uuid=product_uuid,
            fetched_at=_now_utc(),
            payload_json=json.dumps(payload),
        )
        db.add(row)
        db.commit()
        return {"ok": True, "product_uuid": product_uuid, "cached_at": row.fetched_at.isoformat()}
    finally:
        db.close()

def _cache_get_latest(product_uuid: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        row = (
            db.query(BasePriceCache)
            .filter(BasePriceCache.product_uuid == product_uuid)
            .order_by(BasePriceCache.fetched_at.desc())
            .first()
        )
        if not row:
            return None
        return json.loads(row.payload_json)
    finally:
        db.close()

@app.post("/doorhangers/import/{product_uuid}")
def doorhangers_import(product_uuid: str):
    """
    Pull baseprices from 4over and cache them.
    """
    payload = four_over_request("GET", f"/printproducts/products/{product_uuid}/baseprices")
    meta = _cache_set_single(product_uuid, payload)
    entities = payload.get("entities", []) if isinstance(payload, dict) else []
    return {"ok": True, **meta, "baseprices_count": len(entities)}

@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_cached_baseprices(product_uuid: str):
    cached = _cache_get_latest(product_uuid)
    if not cached:
        raise HTTPException(status_code=404, detail="No cached baseprices for this product_uuid. Run POST /doorhangers/import/{product_uuid}")
    return cached

def _normalize_optiongroups(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Defensive parsing: 4over responses have varied field naming depending on API version.
    We normalize into:
      [{ option_group_uuid, name, minoccurs, maxoccurs, options: [{option_uuid, option_name, option_description, option_prices?}] }]
    """
    entities = raw.get("entities", [])
    if not isinstance(entities, list):
        return []

    out: List[Dict[str, Any]] = []
    for g in entities:
        if not isinstance(g, dict):
            continue

        group_uuid = g.get("option_group_uuid") or g.get("product_option_group_uuid") or g.get("id") or g.get("uuid")
        name = g.get("name") or g.get("option_group_name") or g.get("group_name") or ""
        minoccurs = g.get("minoccurs", g.get("minOccurs", g.get("min_occurs", "0")))
        maxoccurs = g.get("maxoccurs", g.get("maxOccurs", g.get("max_occurs", "0")))

        raw_opts = g.get("options") or g.get("values") or []
        opts_out: List[Dict[str, Any]] = []
        if isinstance(raw_opts, list):
            for o in raw_opts:
                if not isinstance(o, dict):
                    continue
                opts_out.append({
                    "option_uuid": o.get("option_uuid") or o.get("id") or o.get("uuid"),
                    "option_name": o.get("option_name") or o.get("name") or "",
                    "option_description": o.get("option_description") or o.get("description") or "",
                    "option_prices": o.get("option_prices") or o.get("prices") or None,
                })

        out.append({
            "option_group_uuid": group_uuid,
            "name": name,
            "minoccurs": str(minoccurs),
            "maxoccurs": str(maxoccurs),
            "options": opts_out,
        })
    return out

@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(..., description="4over product UUID")):
    """
    Pull live optiongroups from 4over and return normalized output.
    """
    raw = four_over_request("GET", f"/printproducts/products/{product_uuid}/optiongroups")
    normalized = _normalize_optiongroups(raw)
    return {"product_uuid": product_uuid, "option_groups": normalized}

def _find_baseprice(entities: List[Dict[str, Any]], runsize: str, colorspec: str) -> Optional[Tuple[float, Dict[str, Any]]]:
    """
    entities item example (per docs):
      product_baseprice, runsize, colorspec, can_group_ship ...
    """
    for row in entities:
        try:
            r = str(row.get("runsize", "")).strip()
            c = str(row.get("colorspec", "")).strip()
            if r == str(runsize).strip() and c == str(colorspec).strip():
                price = float(row.get("product_baseprice"))
                return price, row
        except Exception:
            continue
    return None

@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str,
    runsize: str,
    colorspec: str,
    markup_pct: float = 25.0,
    auto_import: bool = True,
):
    """
    Quote = baseprice * (1 + markup_pct/100)
    Uses cached baseprices; optionally auto-imports if cache missing.
    """
    cached = _cache_get_latest(product_uuid)

    if not cached and auto_import:
        payload = four_over_request("GET", f"/printproducts/products/{product_uuid}/baseprices")
        _cache_set_single(product_uuid, payload)
        cached = payload

    if not cached:
        raise HTTPException(status_code=404, detail="No cache for product. Run POST /doorhangers/import/{product_uuid}")

    entities = cached.get("entities", [])
    if not isinstance(entities, list) or not entities:
        raise HTTPException(status_code=500, detail="Cached baseprices malformed or empty")

    hit = _find_baseprice(entities, runsize=runsize, colorspec=colorspec)
    if not hit:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "No baseprice match for runsize/colorspec",
                "product_uuid": product_uuid,
                "runsize": runsize,
                "colorspec": colorspec,
                "available_runsizes": sorted(list({str(e.get('runsize')) for e in entities if isinstance(e, dict)}))[:50],
                "available_colorspecs": sorted(list({str(e.get('colorspec')) for e in entities if isinstance(e, dict)}))[:50],
            }
        )

    base_price, row = hit
    multiplier = 1.0 + (float(markup_pct) / 100.0)
    sell_price = round(base_price * multiplier, 2)

    return {
        "product_uuid": product_uuid,
        "runsize": str(runsize),
        "colorspec": str(colorspec),
        "base_price": round(base_price, 2),
        "markup_pct": float(markup_pct),
        "sell_price": sell_price,
        "can_group_ship": row.get("can_group_ship", None),
        "source": "baseprice_cache_latest",
    }

# -----------------------------
# Global error handler (prettier JSON)
# -----------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    # Avoid leaking secrets; keep it concise
    return JSONResponse(status_code=500, content={"error": "server_error", "detail": str(exc)[:800]})
