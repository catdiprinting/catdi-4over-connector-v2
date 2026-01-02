import os
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector")


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def ok(resp, data):
    return {"ok": True, "http_code": resp.status_code, "data": data}


def fail(resp, data):
    # normalize to your style
    # Some 4over errors return {status:"error", ...}
    return {"ok": False, "http_code": resp.status_code, "data": data}


def api_path(path: str) -> str:
    """
    Builds /printproducts/... paths.
    """
    prefix = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")
    return f"/{prefix}/{path.lstrip('/')}"


def fetch_product_and_prices(client: FourOverClient, product_uuid: str):
    """
    Returns (product_json, baseprices_json).
    """
    product_resp = client.get(api_path(f"products/{product_uuid}"))
    product_json = safe_json(product_resp)

    base_resp = client.get(api_path(f"products/{product_uuid}/baseprices"), params={"max": 500, "offset": 0})
    base_json = safe_json(base_resp)

    return product_json, base_json


def build_matrix(product_json: dict, baseprices_json: dict):
    """
    Takes the product detail json and baseprices json and returns:
      - product metadata
      - options grouped by friendly names
      - baseprices entities
    """
    out = {
        "product_uuid": product_json.get("product_uuid"),
        "product_code": product_json.get("product_code"),
        "description": product_json.get("product_description"),
        "options": {},
        "baseprices": baseprices_json.get("entities", []),
    }

    option_groups = product_json.get("product_option_groups", []) or []
    for og in option_groups:
        name = (og.get("product_option_group_name") or "").strip()
        options = og.get("options", []) or []

        key = name.lower().replace(" ", "_")
        if not key:
            continue

        out["options"][key] = options

    return out


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "build": os.getenv("BUILD_TAG", "matrix-quote-v1")}


@app.get("/debug/auth")
def debug_auth():
    """
    Shows that env vars are present and signatures are stable (without leaking keys).
    """
    try:
        c = FourOverClient()
        # sample canonical strings
        canonical_get = "/whoami?apikey=" + c.apikey
        sig_get = c._hmac_sha256(canonical_get)

        canonical_post = "/printproducts/orders"
        sig_post = c._hmac_sha256(canonical_post)

        return {
            "base_url": c.base_url,
            "api_prefix": c.api_prefix,
            "timeout": c.timeout,
            "apikey_present": bool(c.apikey),
            "private_key_present": bool(c.private_key),
            "apikey_edge": c.apikey[:5],
            "private_key_len": len(c.private_key),
            "sig_GET_edge": f"{sig_get[:6]}...{sig_get[-6:]}",
            "sig_POST_edge": f"{sig_post[:6]}...{sig_post[-6:]}",
            "note": "GET uses query auth; POST uses Authorization: API apikey:signature",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/4over/whoami")
def whoami():
    try:
        client = FourOverClient()
        resp = client.get("/whoami")
        data = safe_json(resp)
        if resp.status_code >= 400:
            return fail(resp, data)
        return ok(resp, data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/4over/categories")
def categories(max: int = Query(50), offset: int = Query(0)):
    try:
        client = FourOverClient()
        resp = client.get(api_path("categories"), params={"max": max, "offset": offset})
        data = safe_json(resp)
        if resp.status_code >= 400:
            return fail(resp, data)
        return ok(resp, data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = Query(25), offset: int = Query(0)):
    try:
        client = FourOverClient()
        resp = client.get(api_path(f"categories/{category_uuid}/products"), params={"max": max, "offset": offset})
        data = safe_json(resp)
        if resp.status_code >= 400:
            return fail(resp, data)
        return ok(resp, data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    """
    Returns product details INCLUDING option groups by calling /printproducts/products/{uuid}
    """
    try:
        client = FourOverClient()
        resp = client.get(api_path(f"products/{product_uuid}"))
        data = safe_json(resp)
        if resp.status_code >= 400:
            return fail(resp, data)
        return ok(resp, data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = Query(200), offset: int = Query(0)):
    """
    Calls /printproducts/products/{uuid}/baseprices
    """
    try:
        client = FourOverClient()
        resp = client.get(api_path(f"products/{product_uuid}/baseprices"), params={"max": max, "offset": offset})
        data = safe_json(resp)
        if resp.status_code >= 400:
            return fail(resp, data)
        return ok(resp, data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.get("/matrix/{product_uuid}")
def matrix(product_uuid: str):
    """
    Returns a friendly “matrix” object: option groups + base prices.
    """
    try:
        client = FourOverClient()
        product_json, baseprices_json = fetch_product_and_prices(client, product_uuid)

        # If either call returned error style, bubble it up
        if isinstance(product_json, dict) and product_json.get("status
