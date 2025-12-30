# doorhangers.py
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text as sql_text

from fourover_client import FourOverClient
from db import get_db
from models import Product, ProductOptionGroup, ProductOptionValue, ProductBasePrice

DOORHANGERS_CATEGORY_UUID = "5cacc269-e6a8-472d-91d6-792c4584cae8"

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])

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


def _entities(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("entities"), list):
        return payload["entities"]
    if isinstance(payload, list):
        return payload
    return []


def _dedupe_by_key(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen = {}
    for r in rows:
        k = r.get(key)
        if k and k not in seen:
            seen[k] = r
    return list(seen.values())


@router.get("/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    path = f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products"
    r, dbg = four_over().get(path, params={"max": max, "offset": offset})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}

    data = r.json()
    items = _entities(data)
    return {"count": len(items), "products": items}


@router.get("/product/{product_uuid}/optiongroups")
def optiongroups(product_uuid: str):
    path = f"/printproducts/products/{product_uuid}/optiongroups"
    r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()


@router.get("/product/{product_uuid}/baseprices")
def baseprices(product_uuid: str):
    path = f"/printproducts/products/{product_uuid}/baseprices"
    r, dbg = four_over().get(path, params={"max": 10000, "offset": 0})
    if not r.ok:
        return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
    return r.json()


@router.post("/reset_tester_tables")
def reset_tester_tables(db: Session = Depends(get_db)):
    """
    Wipes ONLY the tester tables used by this doorhangers pricing tester.
    """
    db.execute(sql_text("TRUNCATE TABLE product_option_values RESTART IDENTITY CASCADE"))
    db.execute(sql_text("TRUNCATE TABLE product_option_groups RESTART IDENTITY CASCADE"))
    db.execute(sql_text("TRUNCATE TABLE product_baseprices RESTART IDENTITY CASCADE"))
    db.execute(sql_text("TRUNCATE TABLE products RESTART IDENTITY CASCADE"))
    db.commit()
    return {"ok": True}


@router.post("/import/{product_uuid}")
def import_product_bundle(
    product_uuid: str,
    db: Session = Depends(get_db),
):
    """
    Pulls from 4over LIVE and imports into Postgres:
      - products row
      - optiongroups + option values
      - baseprices matrix (runsize/colorspec combos)
    Safe to re-run because we delete+reinsert per-product.
    """
    # 1) fetch product record (from category list; easiest)
    cat_path = f"/printproducts/categories/{DOORHANGERS_CATEGORY_UUID}/products"
    r, _dbg = four_over().get(cat_path, params={"max": 5000, "offset": 0})
    if not r.ok:
        raise HTTPException(status_code=r.status_code, detail=_json_or_text(r))

    items = _entities(r.json())
    p = next((x for x in items if x.get("product_uuid") == product_uuid), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found in category list")

    # 2) fetch optiongroups + baseprices
    og = optiongroups(product_uuid)
    bp = baseprices(product_uuid)

    og_items = _entities(og)
    bp_items = _entities(bp)

    # 3) upsert product
    prod_row = {
        "product_uuid": product_uuid,
        "product_code": p.get("product_code"),
        "product_description": p.get("product_description"),
        "categories_path": p.get("categories") or p.get("product_categories"),
        "optiongroups_path": p.get("product_option_groups"),
        "baseprices_path": p.get("product_base_prices"),
    }

    # 4) delete existing per-product rows (so reimport is clean)
    db.query(ProductOptionValue).filter(
        ProductOptionValue.product_option_group_uuid.in_(
            db.query(ProductOptionGroup.product_option_group_uuid).filter(ProductOptionGroup.product_uuid == product_uuid)
        )
    ).delete(synchronize_session=False)

    db.query(ProductOptionGroup).filter(ProductOptionGroup.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(ProductBasePrice).filter(ProductBasePrice.product_uuid == product_uuid).delete(synchronize_session=False)
    db.query(Product).filter(Product.product_uuid == product_uuid).delete(synchronize_session=False)
    db.commit()

    # 5) insert product
    db.execute(pg_insert(Product.__table__).values([prod_row]).on_conflict_do_nothing(index_elements=["product_uuid"]))

    # 6) option groups + values
    pog_rows: List[Dict[str, Any]] = []
    pov_rows: List[Dict[str, Any]] = []

    for g in og_items:
        guid = g.get("product_option_group_uuid") or g.get("option_group_uuid") or g.get("uuid")
        if not guid:
            continue

        # NOTE: your working response uses: name/minoccurs/maxoccurs and values[]
        pog_rows.append(
            {
                "product_option_group_uuid": str(guid),
                "product_uuid": product_uuid,
                "name": g.get("name") or g.get("product_option_group_name"),
                "minoccurs": str(g.get("minoccurs") or ""),
                "maxoccurs": str(g.get("maxoccurs") or ""),
            }
        )

        values = g.get("values") or g.get("options") or []
        if isinstance(values, list):
            for v in values:
                vuid = v.get("product_option_value_uuid") or v.get("option_uuid") or v.get("uuid") or v.get("option_value_uuid")
                if not vuid:
                    continue

                pov_rows.append(
                    {
                        "product_option_value_uuid": str(vuid),
                        "product_option_group_uuid": str(guid),
                        "name": v.get("name") or v.get("option_name"),
                        "code": v.get("code") or v.get("option_name"),
                        "sort": v.get("sort") if isinstance(v.get("sort"), int) else None,
                        # optional matrix fields if present
                        "runsize_uuid": v.get("runsize_uuid"),
                        "runsize": v.get("runsize"),
                        "colorspec_uuid": v.get("colorspec_uuid"),
                        "colorspec": v.get("colorspec"),
                        "turnaround_uuid": v.get("turnaround_uuid"),
                        "turnaround": v.get("turnaround"),
                    }
                )

    pog_rows = _dedupe_by_key(pog_rows, "product_option_group_uuid")
    pov_rows = _dedupe_by_key(pov_rows, "product_option_value_uuid")

    if pog_rows:
        db.execute(pg_insert(ProductOptionGroup.__table__).values(pog_rows))

    if pov_rows:
        db.execute(pg_insert(ProductOptionValue.__table__).values(pov_rows))

    # 7) base prices matrix
    pbp_rows: List[Dict[str, Any]] = []
    for x in bp_items:
        buid = x.get("base_price_uuid") or x.get("product_baseprice_uuid") or x.get("uuid")
        if not buid:
            continue
        pbp_rows.append(
            {
                "base_price_uuid": str(buid),
                "product_uuid": product_uuid,
                "product_baseprice": x.get("product_baseprice") or x.get("price"),
                "runsize_uuid": x.get("runsize_uuid"),
                "runsize": x.get("runsize"),
                "colorspec_uuid": x.get("colorspec_uuid"),
                "colorspec": x.get("colorspec"),
                "turnaround_uuid": x.get("turnaround_uuid"),
                "turnaround": x.get("turnaround"),
                "can_group_ship": bool(x.get("can_group_ship", False)) if x.get("can_group_ship") is not None else None,
            }
        )

    pbp_rows = _dedupe_by_key(pbp_rows, "base_price_uuid")

    if pbp_rows:
        db.execute(pg_insert(ProductBasePrice.__table__).values(pbp_rows))

    db.commit()

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "option_groups": len(pog_rows),
        "option_values": len(pov_rows),
        "base_prices": len(pbp_rows),
    }


@router.get("/matrix_keys")
def matrix_keys(product_uuid: str, db: Session = Depends(get_db)):
    """
    Returns unique runsize/colorspec UUIDs seen in base price matrix for a product.
    """
    rows = db.query(ProductBasePrice).filter(ProductBasePrice.product_uuid == product_uuid).all()

    run_map = {}
    col_map = {}

    for r in rows:
        if r.runsize_uuid:
            run_map[r.runsize_uuid] = r.runsize or r.runsize_uuid
        if r.colorspec_uuid:
            col_map[r.colorspec_uuid] = r.colorspec or r.colorspec_uuid

    runsizes = [{"uuid": k, "label": v} for k, v in sorted(run_map.items(), key=lambda kv: str(kv[1]))]
    colorspecs = [{"uuid": k, "label": v} for k, v in sorted(col_map.items(), key=lambda kv: str(kv[1]))]

    return {"ok": True, "product_uuid": product_uuid, "runsizes": runsizes, "colorspecs": colorspecs}


@router.get("/price")
def price(product_uuid: str, runsize_uuid: str, colorspec_uuid: str, db: Session = Depends(get_db)):
    row = (
        db.query(ProductBasePrice)
        .filter(
            ProductBasePrice.product_uuid == product_uuid,
            ProductBasePrice.runsize_uuid == runsize_uuid,
            ProductBasePrice.colorspec_uuid == colorspec_uuid,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No base price found for that combo")

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "runsize_uuid": runsize_uuid,
        "colorspec_uuid": colorspec_uuid,
        "runsize": row.runsize,
        "colorspec": row.colorspec,
        "base_price": float(row.product_baseprice) if row.product_baseprice is not None else None,
        "can_group_ship": row.can_group_ship,
    }
