from fastapi import FastAPI
from config import SERVICE_NAME, PHASE, BUILD
from db import ping_db
from doorhangers import router as doorhangers_router

app = FastAPI(title=SERVICE_NAME)

@app.get("/version")
def version():
    return {
        "service": SERVICE_NAME,
        "phase": PHASE,
        "build": BUILD,
    }

@app.get("/diag")
def diag():
    return {
        "service": SERVICE_NAME,
        "phase": PHASE,
        "build": BUILD,
        "status": "OK",
    }

@app.get("/db/ping")
def db_ping():
    ping_db()
    return {"ok": True}

app.include_router(doorhangers_router)
