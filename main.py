from fastapi import FastAPI, HTTPException

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "BOOT_SAFE_WITH_ROUTER_DIAGNOSTICS_V2",
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
        from db import ensure_schema  # local import on purpose
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})


# --- Doorhangers router loading (never crash boot) ---
DOORHANGERS_ROUTER_OK = False
DOORHANGERS_ROUTER_ERROR = None

try:
    from doorhangers import router as doorhangers_router  # expects doorhangers.py
    app.include_router(doorhangers_router)
    DOORHANGERS_ROUTER_OK = True
except Exception as err:
    DOORHANGERS_ROUTER_OK = False
    DOORHANGERS_ROUTER_ERROR = str(err)


@app.get("/_router_error")
def router_error():
    # Always returns 200 with status so we can see what broke without logs
    return {
        "ok": DOORHANGERS_ROUTER_OK,
        "router": "doorhangers",
        "error": DOORHANGERS_ROUTER_ERROR,
        "hint": "If error says ModuleNotFoundError: doorhangers, confirm file is named exactly doorhangers.py (no spaces, no parentheses).",
    }
