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
        for o in (g.get("options") or []):
            out.append({
                "option_uuid": o.get("option_uuid"),
                "option_name": o.get("option_name"),
                "option_description": o.get("option_description"),
                "option_prices": o.get("option_prices"),
                "runsize": o.get("runsize"),
                "runsize_uuid": o.get("runsize_uuid"),
                "colorspec": o.get("colorspec"),
                "colorspec_uuid": o.get("colorspec_uuid"),
            })
        return out

    # baseprices condensed
    bp_entities = (baseprices.get("entities") or [])
    bp_rows = []
    for row in bp_entities:
        bp_rows.append({
            "runsize": row.get("runsize"),
            "runsize_uuid": row.get("runsize_uuid"),
            "colorspec": row.get("colorspec"),
            "colorspec_uuid": row.get("colorspec_uuid"),
            "product_baseprice": row.get("product_baseprice"),
            "base_price_uuid": row.get("base_price_uuid"),
        })

    return {
        "product_uuid": product.get("product_uuid"),
        "product_code": product.get("product_code"),
        "product_description": product.get("product_description"),
        "categories": product.get("categories", []),
        "options": {
            "size": list_options("Size"),
            "stock": list_options("Stock"),
            "coating": list_options("Coating"),
            "colorspec": list_options("Colorspec"),
            "runsize": list_options("Runsize"),
            "turnaround": list_options("Turn Around Time"),
            "additional_options": list_options("Additional Options"),
        },
        "baseprices": bp_rows,
    }


@app.get("/quote")
def quote(
    product_uuid: str = Query(...),
    runsize: str = Query(..., description="e.g. 1000, 2500, 5000"),
    colorspec: str = Query(..., description="e.g. 4/0, 4/1, 4/4"),
    turnaround_option_uuid: str | None = Query(None, description="optional option_uuid from Turn Around Time group"),
):
    """
    Returns base price for the product+qty+colorspec.
    If turnaround_option_uuid is provided, we ALSO try to fetch the turnaround price table via option_prices URL.
    """
    client = FourOverClient()
    product, baseprices = _get_product_and_prices(client, product_uuid)

    # 1) Find baseprice row
    bp_entities = (baseprices.get("entities") or [])
    match = None
    for row in bp_entities:
        if str(row.get("runsize")) == str(runsize) and str(row.get("colorspec")) == str(colorspec):
            match = row
            break

    if not match:
        return {
            "ok": False,
            "message": "No base price match for runsize/colorspec on this product_uuid",
            "product_uuid": product_uuid,
            "runsize": runsize,
            "colorspec": colorspec,
            "hint": "Try /matrix/{product_uuid} to see valid runsize/colorspec combos",
        }

    result = {
        "ok": True,
        "product_uuid": product_uuid,
        "product_code": product.get("product_code"),
        "product_description": product.get("product_description"),
        "runsize": runsize,
        "colorspec": colorspec,
        "base_price_uuid": match.get("base_price_uuid"),
        "product_baseprice": match.get("product_baseprice"),
        "turnaround": None,
    }

    # 2) Optional: attempt to pull turnaround price info (if present)
    if turnaround_option_uuid:
        groups = _group_map(product)
        tg = groups.get("turn around time")
        if not tg:
            result["turnaround"] = {"ok": False, "message": "Turn Around Time group not present on product"}
            return result

        opt = None
        for o in (tg.get("options") or []):
            if o.get("option_uuid") == turnaround_option_uuid:
                opt = o
                break

        if not opt:
            result["turnaround"] = {"ok": False, "message": "turnaround_option_uuid not found on this product"}
            return result

        prices_url = opt.get("option_prices")
        if not prices_url:
            result["turnaround"] = {"ok": False, "message": "No option_prices URL on turnaround option"}
            return result

        pr = client.get_url(prices_url, params={"max": 200, "offset": 0})
        try:
            turnaround_prices = pr.json()
        except Exception:
            turnaround_prices = {"raw": pr.text}

        result["turnaround"] = {
            "ok": pr.ok,
            "http_code": pr.status_code,
            "option_uuid": turnaround_option_uuid,
            "option_name": opt.get("option_name"),
            "option_description": opt.get("option_description"),
            "prices_url": prices_url,
            "prices_data": turnaround_prices,
        }

    return result
