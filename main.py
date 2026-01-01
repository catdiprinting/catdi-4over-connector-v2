import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from fourover_client import FourOverClient, FourOverAuthError, FourOverHTTPError, FourOverError

# Load local .env only if it exists (Railway doesn't need it)
if os.path.exists(".env"):
    load_dotenv()

app = FastAPI(title="Catdi 4over Connector", version="v2-bridge")


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector-v2", "phase": "bridge"}


@app.get("/debug/auth")
def debug_auth():
    def present(name: str) -> bool:
        return bool((os.getenv(name) or "").strip())

    return {
        "FOUR_OVER_BASE_URL": (os.getenv("FOUR_OVER_BASE_URL") or "https://api.4over.com").strip(),
        "FOUR_OVER_API_PREFIX": (os.getenv("FOUR_OVER_API_PREFIX") or "").strip(),
        "FOUR_OVER_APIKEY_present": present("FOUR_OVER_APIKEY"),
        "FOUR_OVER_PRIVATE_KEY_present": present("FOUR_OVER_PRIVATE_KEY"),
        "FOUR_OVER_TIMEOUT": (os.getenv("FOUR_OVER_TIMEOUT") or "30").strip(),
    }


def _client() -> FourOverClient:
    return FourOverClient()


@app.get("/4over/whoami")
def whoami():
    try:
        data = _client().get("/whoami")
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": "auth_error", "detail": str(e)})
    except FourOverHTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "upstream_error", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "client_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})


# -------------------------------------------------------------------
# Catalog bridge endpoints (based on old site behavior)
# -------------------------------------------------------------------

@app.get("/4over/categories")
def categories(max: int = 200, offset: int = 0):
    """
    Old PHP used max/offset pagination. We'll keep that.
    NOTE: If this 404s, set FOUR_OVER_API_PREFIX=printproducts and redeploy.
    """
    try:
        data = _client().get("/categories", params={"max": max, "offset": offset})
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "categories_failed", "detail": str(e)})


@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 200, offset: int = 0):
    try:
        data = _client().get(f"/categories/{category_uuid}/products", params={"max": max, "offset": offset})
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "category_products_failed", "detail": str(e)})


@app.get("/4over/products/{product_uuid}")
def product_detail(product_uuid: str):
    try:
        data = _client().get(f"/products/{product_uuid}")
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "product_detail_failed", "detail": str(e)})


@app.get("/4over/products/{product_uuid}/options")
def product_options(product_uuid: str):
    """
    Best-effort endpoint: many 4over products expose options under an options endpoint.
    If this 404s, we’ll adjust path based on actual 4over response quickly.
    """
    try:
        data = _client().get(f"/products/{product_uuid}/options")
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "product_options_failed", "detail": str(e)})


@app.post("/4over/products/{product_uuid}/quote")
def product_quote(product_uuid: str, payload: dict):
    """
    Old system ultimately calls productquote with the selected option/value IDs.
    We accept the payload and pass through.

    If this 404s, set FOUR_OVER_API_PREFIX=printproducts and try again, or we adjust this endpoint path.
    """
    try:
        # Common patterns include /productquote or /products/{id}/quote
        # We'll try /productquote first with product_uuid in payload (easy to change later).
        payload = dict(payload or {})
        payload.setdefault("product_uuid", product_uuid)

        data = _client().post("/productquote", json=payload)
        return {"ok": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "product_quote_failed", "detail": str(e)})
