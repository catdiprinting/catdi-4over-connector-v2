from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Any, Dict, List, Optional
import re

from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "DOORHANGERS_PHASE1"
BUILD = "BASELINE_WHOAMI_WORKING_2025-12-29"

# Door Hangers category UUID you provided
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


def _extract_size_from_desc(desc: str) -> Optional[str]:
    """
    Pull sizes like: 3.5" X 8.5" or 4.25" X 11" from product_description
    """
    if not desc:
        return None
    m = re.search(r'(\d+(\.\d+)?)"\s*X\s*(\d+(\.\d+)?)"', desc)
    if not m:
        return None
    return f'{m.group(1)}" x {m.group(3)}"'


def _extract_stock_from_desc(desc: str) -> Optional[str]:
    """
    Very lightweight parsing based on your examples:
      - 14PT
      - 16PT
      - 100LB GLOSS BOOK
      - 100LB GLOSS Cover
    We'll refine later using optiongroups (source of truth).
    """
    if not desc:
        return None
    if "14PT" in desc:
        return "14PT"
    if "16PT" in desc:
        return "16PT"
    if "100LB" in desc and "BOOK" in desc:
        return "100LB Gloss Book"
    if "100LB" in desc and "Cover" in desc:
        return "100LB Gloss Cover"
    return None


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/4over/whoami")
def whoami():
    try:
        r, _dbg = four_over().get("/whoami", params={})
        if not r.ok:
            return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/printproducts/categories")
def categories(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    try:
        r, dbg = four_over().get("/printproducts/categories", params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
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


# ---------------------------
# Door Hangers: Phase 1
# ---------------------------

@app.get("/doorhangers/products")
def doorhangers_products(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Pull the Door Hangers product list (the exact response you pasted).
    """
    return category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)


@app.get("/doorhangers/products/summary")
def doorhangers_products_summary(max: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """
    Quick summarizer: derive Size + Stock + Coating hint from description/code.
    (Optiongroups will be source of truth later.)
    """
    data = category_products(DOORHANGERS_CATEGORY_UUID, max=max, offset=offset)

    if isinstance(data, dict) and "entities" in data:
        items = data["entities"]
    else:
        items = data if isinstance(data, list) else []

    out = []
    for p in items:
        desc = p.get("product_description", "") or ""
        code = p.get("product_code", "") or ""
        size = _extract_size_from_desc(desc)
        stock = _extract_stock_from_desc(desc)

        coating = None
        # from code fragments: DHAQ, DHUV, DHUC, DHUVFR, DHSA
        if "DHAQ" in code:
            coating = "AQ"
        elif "DHSA" in code:
            coating = "Satin AQ"
        elif "DHUVFR" in code:
            coating = "Full UV Front Only"
        elif "DHUV" in code:
            coating = "UV"
        elif "DHUC" in code:
            coating = "Uncoated"

        out.append(
            {
                "product_uuid": p.get("product_uuid"),
                "product_code": code,
                "size_hint": size,
                "stock_hint": stock,
                "coating_hint": coating,
                "product_description": desc,
                "optiongroups_path": p.get("product_option_groups"),
                "baseprices_path": p.get("product_base_prices"),
            }
        )

    return {"count": len(out), "items": out}


@app.get("/doorhangers/product/{product_uuid}/optiongroups")
def doorhangers_optiongroups(product_uuid: str):
    """
    Pull option groups for a single product (this is where dropdown options live).
    """
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
    """
    Pull base prices for a single product (this is where quantity/turnaround pricing lives).
    """
    try:
        path = f"/printproducts/products/{product_uuid}/baseprices"
        r, dbg = four_over().get(path, params={"max": 5000, "offset": 0})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/doorhangers/help")
def doorhangers_help():
    """
    Handy list of hyperlinked tests for Door Hangers.
    """
    base = "https://web-production-009a.up.railway.app"
    return {
        "tests": {
            "whoami": f"{base}/4over/whoami",
            "doorhangers_products": f"{base}/doorhangers/products?max=1000&offset=0",
            "doorhangers_summary": f"{base}/doorhangers/products/summary?max=1000&offset=0",
            "pick_a_product_uuid_then_optiongroups": f"{base}/doorhangers/product/<PRODUCT_UUID>/optiongroups",
            "pick_a_product_uuid_then_baseprices": f"{base}/doorhangers/product/<PRODUCT_UUID>/baseprices",
        },
        "doorhangers_category_uuid": DOORHANGERS_CATEGORY_UUID,
        "note": "Step 1: Get products. Step 2: Pick a product_uuid and fetch optiongroups + baseprices.",
    }
