from fastapi import FastAPI, HTTPException

from db import ping_db
from fourover_client import call_4over

app = FastAPI(title="Catdi 4over Connector", version="0.0.3")


@app.get("/")
def root():
    return {"ok": True, "hint": "try /health, /version, /db-check, /4over/whoami, /docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.6", "build": "4over-ping-enabled"}


@app.get("/db-check")
def db_check():
    try:
        ping_db()
        return {"db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB check failed: {type(e).__name__}: {e}")


@app.get("/4over/ping")
async def fourover_ping():
    """
    Simple reachability test. Uses /whoami because it's the classic auth test,
    but you can swap to any lightweight endpoint you know exists.
    """
    result, debug = await call_4over("/whoami")
    return {"result": result, "debug": debug}


@app.get("/4over/whoami")
async def fourover_whoami():
    result, debug = await call_4over_probe("/whoami")
    return {"result": result, "debug": debug}
