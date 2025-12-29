import os
from fastapi import FastAPI, HTTPException
from fourover_client import FourOverClient
from db import init_db

app = FastAPI(title="Catdi 4over Connector", version="0.8.1")

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
    return {"service": "catdi-4over-connector", "phase": "0.8.1", "build": "catalog-explorer-enabled"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/version")
def version():
    return {"version": "0.8.1"}

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
    # Don’t leak secrets; just confirm presence + host/db type
    return {
        "has_FOUR_OVER_APIKEY": bool(os.getenv("FOUR_OVER_APIKEY")),
        "has_FOUR_OVER_PRIVATE_KEY": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_BASE_URL": os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        "db_is_sqlite": os.getenv("DATABASE_URL", "").startswith("sqlite"),
        "db_url_present": bool(os.getenv("DATABASE_URL")),
    }

@app.get("/4over/whoami")
def fourover_whoami():
    client = get_client()
    return client.request("GET", "/whoami")

@app.get("/4over/explore")
def fourover_explore(limit: int = 15):
    client = get_client()
    candidates = [
        "/products",
        "/catalog",
        "/categories",
        "/pricing",
        "/price",
        "/turnaround",
    ]
    results = []
    for path in candidates[:limit]:
        results.append({"path": path, **client.request("GET", path)})
    return {"ok": True, "tested": len(results), "results": results}

@app.get("/4over/explore-path")
def fourover_explore_path(path: str, q: str | None = None):
    client = get_client()
    params = {}
    if q:
        params["q"] = q
    return {"ok": True, "path": path, **client.request("GET", path, params=params)}

@app.post("/admin/sync-products")
def sync_products_smoke():
    return {"ok": True, "message": "sync endpoint reached", "note": "Door Hangers sync coming next"}
