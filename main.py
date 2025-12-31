# main.py
from fastapi import FastAPI, HTTPException
from config import settings
from db import Base, engine, db_select_1
from fourover import FourOverClient, FourOverError

app = FastAPI(title="Catdi × 4over Connector")

# create tables (fine for now)
Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {
        "service": settings.SERVICE_NAME,
        "phase": settings.PHASE,
        "build": settings.BUILD,
        "remembered_base_url": "https://web-production-009a.up.railway.app",
    }


@app.get("/version")
def version():
    return {"service": settings.SERVICE_NAME, "phase": settings.PHASE, "build": settings.BUILD}


@app.get("/db/ping")
def db_ping():
    try:
        db_select_1()
        return {"ok": True, "db": "reachable"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB ping failed: {type(e).__name__}: {str(e)}")


@app.get("/4over/whoami")
def fourover_whoami():
    try:
        client = FourOverClient()
        return {"ok": True, "data": client.whoami()}
    except FourOverError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {str(e)}")
