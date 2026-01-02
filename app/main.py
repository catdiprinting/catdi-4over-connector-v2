from fastapi import FastAPI, HTTPException, Query
from app.fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector")


# ----------------
# Health + debug
# ----------------

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "catdi-4over-connector",
        "build": "matrix-quote-v1",
    }


@app.get("/debug/auth")
def debug_auth():
    try:
        client = FourOverClient()
        sig = client._signature("GET")
        return {
            "ok": True,
            "apikey_present": True,
            "private_key_present": True,
            "sig_sample": sig[:12] + "...",
            "base_test_url": "https://web-production-009a.up.railway.app/4over/whoami",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------
# 4over passthrough
# ----------------

@app.get("/4over/whoami")
def whoami():
    client = FourOverClient()
    r = client.get("/whoami")
    return {"ok": r.ok, "http_code": r.status_code, "data": r.json()}


@app.get("/4over/categories")
def categories(max: int = 50, offset: int = 0):
    client = FourOverClient()
    r = client.get("/categories", params={"max": max, "offset": offset})
    return {"ok": r.ok, "http_code": r.status_code, "data": r.json()}


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 50, offset: int = 0):
    client = FourOverClient()
    r = client.get(
        f"/categories/{category_uuid}/products",
        params={"max": max, "offset": offset},
    )
    return {"ok": r.ok, "http_code": r.status_code, "data": r.json()}


@app.get("/4over/products/{product_uuid}")
def product_details(product_uuid: str):
    client = FourOverClient()
    r = client.get(f"/products/{product_uuid}")
    return {"ok": r.ok, "http_code": r.status_code, "data": r.json()}


@app.get("/4over/products/{product_uuid}/base-prices")
def product_base_prices(product_uuid: str, max: int = 200, offset: int = 0):
    client = FourOverClient()
    r = client.get(
        f"/products/{product_uuid}/baseprices",
        params={"max": max, "offset": offset},
    )
    return {"ok": r.ok, "http_code": r.status_code, "data": r.json()}


# ----------------
# Helpers
# ----------------

def fetch_product_and_prices(client: FourOverClient, product_uuid: str):
    p = client.get(f"/products/{product_uuid}")
    if not p.ok:
        raise HTTPException(status_code=500, detail="Product fetch failed")

    b = client.get(
        f"/products/{product_uuid}/baseprices",
        params={"max": 1000, "offset": 0},
    )
    if not b.ok:
        raise HTTPException(status_code=500, detail="Baseprice fetch failed")

    return p.json(), b.json()


def group_map(product: dict):
    gm = {}
    for g in product.get("product_option_groups", []):
        name = g.get("product_option_group_name")
        if name:
            gm[name.lower()] = g
    return gm


# ----------------
# MATRIX endpoint
# ----------------

@app.get("/matrix/{product_uuid}")
def matrix(product_uuid: str):
    client = FourOverClient()
    product, baseprices = fetch_product_and_prices(client, product_uuid)

    groups = group_map(product)

    def options(group_name: str):
        g = groups.get(group_name.lower())
        if not g:
            return []
        return g.get("options", [])

    return {
        "product_uuid": product.get("product_uuid"),
        "product_code": product.get("product_code"),
        "description": product.get("product_description"),
        "options": {
            "size": options("Size"),
            "stock": options("Stock"),
            "coating": options("Coating"),
            "colorspec": options("Colorspec"),
            "runsize": options("Runsize"),
            "turnaround": options("Turn Around Time"),
        },
        "baseprices": baseprices.get("entities", []),
    }


# ----------------
# QUOTE endpoint
# ----------------

@app.get("/quote")
def quote(
    product_uuid: str = Query(...),
    runsize: str = Query(...),
    colorspec: str = Query(...),
):
    client = FourOverClient()
    _, baseprices = fetch_product_and_prices(client, product_uuid)

    for row in baseprices.get("entities", []):
        if str(row.get("runsize")) == str(runsize) and str(row.get("colorspec")) == str(colorspec):
            return {
                "ok": True,
                "product_uuid": product_uuid,
                "runsize": runsize,
                "colorspec": colorspec,
                "base_price": row.get("product_baseprice"),
                "base_price_uuid": row.get("base_price_uuid"),
            }

    return {
        "ok": False,
        "message": "No matching base price found",
        "hint": "Use /matrix/{product_uuid} to see valid combinations",
    }
