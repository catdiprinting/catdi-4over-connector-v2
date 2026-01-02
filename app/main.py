from fastapi import FastAPI
from fastapi.responses import JSONResponse
from .fourover import get as four_get, FourOverError

app = FastAPI(title="catdi-4over-connector", version="v2-stable")

@app.get("/")
def root():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/health")
def health():
    return {"ok": True, "status": "healthy"}

@app.get("/debug/auth")
def debug_auth():
    import os
    return {
        "ok": True,
        "has_api_key": bool(os.getenv("FOUR_OVER_APIKEY")),
        "has_private_key": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "base_url": os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
    }

@app.get("/4over/whoami")
def whoami():
    try:
        http_code, body, url = four_get("/whoami")
        ok = http_code == 200
        return {"ok": ok, "http_code": http_code, "data": body, "debug": {"url": url}}
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/4over/categories/{category_uuid}/products")
def category_products(category_uuid: str, max: int = 25, offset: int = 0):
    try:
        http_code, body, url = four_get(
            f"/printproducts/categories/{category_uuid}/products",
            params={"max": max, "offset": offset},
        )
        ok = http_code == 200
        return {"ok": ok, "http_code": http_code, "data": body, "debug": {"url": url}}
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
