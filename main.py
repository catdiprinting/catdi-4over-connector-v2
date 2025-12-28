from fastapi import FastAPI, HTTPException
from db import ping_db

app = FastAPI(title="Catdi 4over Connector", version="0.0.2")

@app.get("/")
def root():
    return {"ok": True, "hint": "try /health, /version, /db-check"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.5", "build": "db-ready"}

@app.get("/db-check")
def db_check():
    try:
        ping_db()
        return {"db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB check failed: {type(e).__name__}: {e}")
