# main.py
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from db import (
    init_db,
    get_db,
    CatalogSize,
    CatalogLine,
    CatalogProduct,
)
from fourover_client import FourOverClient

APP_PHASE = os.getenv("APP_PHASE", "0.7")
BUILD = os.getenv("BUILD", "catalog-db-enabled")
FAMILY_DEFAULT = os.getenv("CATALOG_FAMILY_DEFAULT", "Business Cards")

app = FastAPI(title="catdi-4over-connector", version=APP_PHASE)


@app.on_event("startup")
def _startup() -> None:
    # Creates tables if they don't exist
    init_db()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "catdi-4over-connector", "phase": APP_PHASE, "build": BUILD}


@app.get("/version")
def version() -> Dict[str, Any]:
    return {"service": "catdi-4over-connector", "phase": APP_PHASE, "build": BUILD}


def get_4over() -> FourOverClient:
    # FourOverClient already reads env vars
    return FourOverClient()


@app.get("/4over/whoami")
def fourover_whoami(client: FourOverClient = Depends(get_4over)) -> Dict[str, Any]:
    resp = client.whoami()
    if not resp.get("ok"):
        raise HTTPException(status_code=resp.get("http_status", 500), detail=resp)
    return resp


# -----------------------------
# Catalog parsing helpers
# -----------------------------
def _norm_size(s: str) -> str:
    return (s or "").strip()


def _size_code(display: str) -> str:
    # 2" x 3.5" -> 2X3.5
    d = display.replace('"', "").replace(" ", "")
    d = d.replace("x", "X").replace("X", "X")
    return d


def _extract_size_from_text(text: str) -> Optional[str]:
    """
    Best-effort extractor for common business card sizes.
    You can improve this later, but this prevents crashes now.
    """
    if not text:
        return None
    t = text.lower().replace(" ", "")

    candidates = [
        '2"x3.5"', '2x3.5', "2x3.5in",
        '2.125"x3.375"', '2.125x3.375',
        '2.5"x2.5"', '2.5x2.5',
        '3.5"x2"', '3.5x2',
    ]
    for c in candidates:
        if c.replace('"', "") in t:
            # normalize display formatting
            if "2.125" in c:
                return '2.125" x 3.375"'
            if "2.5x2.5" in c:
                return '2.5" x 2.5"'
            return '2" x 3.5"'
    return None


def _extract_line_from_text(text: str) -> str:
    """
    Best-effort line name grouping.
    This is where '14pt Matte' should become a LINE under family 'Business Cards'
    (not a standalone product by itself).
    """
    if not text:
        return "Unknown Line"
    t = text.strip()

    # Simple keyword bucketing (upgrade later)
    keywords = [
        "14pt", "16pt", "18pt", "100lb", "110lb", "linen", "kraft", "soft touch", "foil",
        "matte", "dull", "uv", "aq", "uncoated", "silk",
    ]
    found = []
    lower = t.lower()
    for k in keywords:
        if k in lower:
            found.append(k)

    if not found:
        # fallback to first ~80 chars
        return t[:80]

    # Make something readable like: "14pt + matte/dull"
    # (still best-effort)
    line = " ".join(found)
    return line.title()


# -----------------------------
# Admin: Sync product catalog (DB cache)
# -----------------------------
@app.post("/admin/sync-products")
def sync_products(
    limit: int = Query(300, ge=1, le=5000),
    family: str = Query(FAMILY_DEFAULT),
    db: Session = Depends(get_db),
    client: FourOverClient = Depends(get_4over),
) -> Dict[str, Any]:
    """
    Pull products from 4over and store into DB as:
      Size -> Line -> Product

    IMPORTANT: This is a first-pass sync. We'll refine parsing once we see real 4over payloads.
    """
    resp = client.list_products(limit=limit)
    if not resp.get("ok"):
        raise HTTPException(status_code=resp.get("http_status", 500), detail=resp)

    data = resp.get("data") or {}
    items = data.get("data") or data.get("items") or data.get("products") or []
    if not isinstance(items, list):
        # don't crash if payload shape differs
        items = []

    created_sizes = 0
    created_lines = 0
    upserted_products = 0

    for p in items:
        # Support multiple possible shapes safely
        product_uuid = str(p.get("uuid") or p.get("id") or "").strip()
        product_code = str(p.get("code") or p.get("product_code") or product_uuid).strip()
        description = str(p.get("description") or p.get("name") or "").strip()

        if not product_uuid:
            # skip bad rows
            continue

        size_display = _extract_size_from_text(description) or '2" x 3.5"'  # fallback
        size_display = _norm_size(size_display)
        size_obj = db.query(CatalogSize).filter(CatalogSize.display == size_display).first()
        if not size_obj:
            size_obj = CatalogSize(display=size_display, code=_size_code(size_display))
            db.add(size_obj)
            db.flush()
            created_sizes += 1

        line_name = _extract_line_from_text(description)
        line_obj = (
            db.query(CatalogLine)
            .filter(CatalogLine.family == family, CatalogLine.name == line_name)
            .first()
        )
        if not line_obj:
            line_obj = CatalogLine(family=family, name=line_name)
            db.add(line_obj)
            db.flush()
            created_lines += 1

        prod_obj = db.query(CatalogProduct).filter(CatalogProduct.product_uuid == product_uuid).first()
        if not prod_obj:
            prod_obj = CatalogProduct(
                product_uuid=product_uuid,
                product_code=product_code,
                description=description,
                size_id=size_obj.id,
                line_id=line_obj.id,
            )
            db.add(prod_obj)
        else:
            # Update in case descriptions change
            prod_obj.product_code = product_code
            prod_obj.description = description
            prod_obj.size_id = size_obj.id
            prod_obj.line_id = line_obj.id

        upserted_products += 1

    db.commit()

    return {
        "ok": True,
        "synced": upserted_products,
        "created_sizes": created_sizes,
        "created_lines": created_lines,
        "family": family,
        "note": "This is a first-pass parse. Next we refine using real 4over product payload structure.",
    }


# -----------------------------
# UX endpoints: fast dropdown support
# -----------------------------
@app.get("/catalog/sizes")
def catalog_sizes(db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = db.query(CatalogSize).order_by(CatalogSize.display.asc()).all()
    return {
        "ok": True,
        "sizes": [{"id": r.id, "display": r.display, "code": r.code} for r in rows],
    }


@app.get("/catalog/lines")
def catalog_lines(
    size_id: int = Query(..., ge=1),
    family: str = Query(FAMILY_DEFAULT),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    q = (
        db.query(CatalogLine)
        .join(CatalogProduct, CatalogProduct.line_id == CatalogLine.id)
        .filter(CatalogProduct.size_id == size_id, CatalogLine.family == family)
        .distinct()
        .order_by(CatalogLine.name.asc())
    )
    rows = q.all()
    return {
        "ok": True,
        "lines": [{"id": r.id, "family": r.family, "name": r.name} for r in rows],
    }


@app.get("/catalog/resolve")
def catalog_resolve(
    size_id: int = Query(..., ge=1),
    line_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Return the products for that size+line (often 1, but could be multiple)
    rows = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.size_id == size_id, CatalogProduct.line_id == line_id)
        .order_by(CatalogProduct.product_code.asc())
        .all()
    )
    return {
        "ok": True,
        "products": [
            {
                "id": r.id,
                "product_uuid": r.product_uuid,
                "product_code": r.product_code,
                "description": r.description,
            }
            for r in rows
        ],
    }
