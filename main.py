from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverClient

APP_NAME = "catdi-4over-connector"
PHASE = "RESET"
BUILD = "doc-signature-method-only-max-offset"

app = FastAPI(title=APP_NAME)

_client: FourOverClient | None = None


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


@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/env")
def env():
    # minimal sanity (no secrets)
    import os
    pk = (os.getenv("FOUR_OVER_PRIVATE_KEY", "") or "").strip()
    ak = (os.getenv("FOUR_OVER_APIKEY", "") or "").strip()
    bu = (os.getenv("FOUR_OVER_BASE_URL", "") or "").strip()
    return {
        "FOUR_OVER_BASE_URL": bu,
        "FOUR_OVER_APIKEY_last4": ak[-4:] if ak else "",
        "FOUR_OVER_PRIVATE_KEY_len": len(pk),
    }


@app.get("/4over/debug/whoami")
def debug_whoami():
    """
    Returns status + response + exact URL used (includes signature) for debugging.
    """
    try:
        r, dbg = four_over().get("/whoami", params={})
        return {
            "ok": r.ok,
            "http_status": r.status_code,
            "body": _json_or_text(r),
            "debug": dbg,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/whoami")
def whoami():
    try:
        r, _dbg = four_over().get("/whoami", params={})
        if not r.ok:
            return JSONResponse(status_code=r.status_code, content=_json_or_text(r))
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --------- Endpoints referenced in the 4over email thread ---------

@app.get("/4over/printproducts/categories")
def categories(
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """
    4over dev: "In each GET API, you need to pass max and offset parameters."
    """
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
    """
    4over dev steps:
      a) GET /printproducts/categories
      b) GET /printproducts/categories/{category_uuid}/products
    """
    try:
        path = f"/printproducts/categories/{category_uuid}/products"
        r, dbg = four_over().get(path, params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/printproducts/products")
def printproducts_products(
    max: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """
    Mentioned in the emails:
      https://api.4over.com/printproducts/products?apikey=catdi&signature=SIGNATURE
    """
    try:
        r, dbg = four_over().get("/printproducts/products", params={"max": max, "offset": offset})
        if not r.ok:
            return {"ok": False, "http_status": r.status_code, "body": _json_or_text(r), "debug": dbg}
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
