import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.2")


def get_client() -> FourOverClient:
    try:
        return FourOverClient()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "phase": "0.8.2", "build": "doorhangers-discovery-enabled"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/version")
def version():
    return {"version": "0.8.2"}


@app.get("/routes")
def routes():
    return {
        "count": len(app.routes),
        "routes": [
            {"path": r.path, "methods": list(r.methods), "name": r.name}
            for r in app.routes
            if hasattr(r, "methods")
        ],
    }


@app.get("/debug/config")
def debug_config():
    db_url = os.getenv("DATABASE_URL", "")
    return {
        "has_FOUR_OVER_APIKEY": bool(os.getenv("FOUR_OVER_APIKEY")),
        "has_FOUR_OVER_PRIVATE_KEY": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_BASE_URL": os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        "db_url_present": bool(db_url),
        "db_is_sqlite": db_url.startswith("sqlite"),
        "db_scheme": (db_url.split(":", 1)[0] if db_url else None),
    }


@app.get("/4over/whoami")
def fourover_whoami():
    client = get_client()
    return client.request("GET", "/whoami")


@app.get("/4over/explore-path")
def fourover_explore_path(path: str, q: str | None = None):
    client = get_client()
    params = {}
    if q:
        params["q"] = q
    return {"ok": True, "path": path, **client.request("GET", path, params=params)}


@app.get("/4over/search-doorhangers")
def search_doorhangers(q: str = "door", max_tests: int = 12):
    """
    Tries a few likely catalog endpoints + a keyword query.
    We are looking for the endpoint that returns Door Hangers category/product IDs.
    """
    client = get_client()

    # Common candidate endpoints seen in 4over integrations
    candidates = [
        ("/printproducts/categories", {"max": 1000}),
        ("/printproducts", {"max": 1000}),
        ("/categories", {"max": 1000}),
        ("/catalog", {"max": 1000}),
        ("/products", {"max": 1000}),
        ("/printproducts/search", {"q": q}),
        ("/products/search", {"q": q}),
        ("/search", {"q": q}),
    ]

    results = []
    for path, params in candidates[:max_tests]:
        resp = client.request("GET", path, params=params)
        results.append({"path": path, "params": params, **resp})

    return {"ok": True, "q": q, "tested": len(results), "results": results}


@app.get("/4over/doorhangers/candidates")
def doorhangers_candidates():
    """
    A second helper that pulls categories and filters locally for anything
    containing "door" or "hanger".
    """
    client = get_client()
    resp = client.request("GET", "/printproducts/categories", params={"max": 2000})

    data = resp.get("data", {})
    items = None

    # We don't know the exact shape; try common keys
    if isinstance(data, dict):
        for key in ("data", "items", "results", "categories"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
    elif isinstance(data, list):
        items = data

    matches = []
    if items:
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "") or it.get("title", "") or "")
            hay = name.lower()
            if "door" in hay or "hanger" in hay:
                matches.append(it)

    return {
        "ok": True,
        "http_status": resp.get("http_status"),
        "raw_ok": resp.get("ok"),
        "match_count": len(matches),
        "matches": matches[:50],  # keep response sane
        "note": "If matches empty, we’ll use /4over/search-doorhangers to find the right endpoint."
    }


@app.post("/admin/sync-products")
def sync_products_smoke():
    return {"ok": True, "message": "sync endpoint reached", "note": "Door Hangers sync coming next"}
