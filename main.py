from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "BOOT_SAFE_WITH_ROUTERS",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    return {"ok": True}


@app.post("/db/init")
def db_init():
    try:
        from db import ensure_schema
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


# Try to load doorhangers router; never crash boot
try:
    from doorhangers import router as doorhangers_router
    app.include_router(doorhangers_router)
except Exception as e:
    # expose a debug endpoint so you can see the import error without logs
    @app.get("/_router_error")
    def router_error():
        return {"ok": False, "router": "doorhangers", "error": str(e)}
