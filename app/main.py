from fastapi import FastAPI, HTTPException, Query
from app.fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector")


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/debug/auth")
def debug_auth():
    try:
        client = FourOverClient()
        sig = client._signature("GET")
        return {
            "base_url": "https://api.4over.com",
            "api_prefix": "printproducts",
            "apikey_present": True,
            "private_key_present": True,
            "sig_sample": sig[:10] + "...",
            "base_test_url": "https://web-production-009a.up.railway.app/4over/whoami",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# 4over passthrough endpoints
# ----------------------------

@app.get("/4over/whoami")
def whoami():
    client = FourOverClient()
    r = client.get("/whoami")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories")
def categories(max: int = 50, offset: int = 0):
    client = FourOverClient()
    r = client.get("/categories", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    client = FourOverClient()
    r = client.get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    client = FourOverClient()
    r = client.get(f"/products/{product_uuid}")
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = 200, offset: int = 0):
    client = FourOverClient()
    r = client.get(f"/products/{product_uuid}/baseprices", params={"max": max, "offset": offset})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.ok, "http_code": r.status_code, "data": data}


# ----------------------------
# NEW: matrix + quote endpoints
# ----------------------------

def _get_product_and_prices(client: FourOverClient, product_uuid: str):
    pr = client.get(f"/products/{product_uuid}")
    if not pr.ok:
        raise HTTPException(status_code=pr.status_code, detail=f"4over product fetch failed: {pr.text}")

    br = client.get(f"/products/{product_uuid}/baseprices", params={"max": 1000, "offset": 0})
    if not br.ok:
        raise HTTPException(status_code=br.status_code, detail=f"4over baseprices fetch failed: {br.text}")

    product = pr.json()
    baseprices = br.json()
    return product, baseprices


def _group_map(product_json: dict):
    groups = product_json.get("product_option_groups") or []
    gm = {}
    for g in groups:
        name = (g.get("product_option_group_name") or "").strip()
        if name:
            gm[name.lower()] = g
    return gm


@app.get("/matrix/{product_uuid}")
def matrix(product_uuid: str):
    """
    Returns a compact view of options + available baseprices.
    Great for building a Woo variation model.
    """
    client = FourOverClient()
    product, baseprices = _get_product_and_prices(client, product_uuid)

    groups = _group_map(product)

    def list_options(group_name: str):
        g = groups.get(group_name.lower())
        if not g:
            return []
        out = []
        for
