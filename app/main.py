from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .db import ping_db
from .fourover_client import client

app = FastAPI(title="catdi-4over-connector", version="1.0.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}

@app.get("/db/ping")
def db_ping():
    try:
        ping_db()
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.get("/4over/whoami")
def whoami():
    try:
        # ROOT endpoint: NO /printproducts prefix
        resp = client.get("/whoami", use_prefix=False)
    except Exception as e:
        # Don't crash the app — show the real env/auth error
        raise HTTPException(status_code=500, detail=str(e))

    if not resp["ok"]:
        raise HTTPException(status_code=resp["http_code"], detail=resp["data"])
    return resp["data"]

@app.get("/4over/categories")
def categories():
    try:
        # Catalog endpoint: USE /printproducts prefix
        resp = client.get("/categories", use_prefix=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not resp["ok"]:
        raise HTTPException(status_code=resp["http_code"], detail=resp["data"])
    return resp["data"]
