from fastapi import FastAPI, HTTPException

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "SAFE_MODE_BOOT_ONLY",
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
    # Lazy import so db.py problems show as 500 (response), not as a crash (502)
    try:
        from db import ensure_schema  # local import on purpose
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "DB init failed", "message": str(e)})
