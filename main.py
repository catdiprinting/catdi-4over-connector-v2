from fastapi import FastAPI
from config import SERVICE_NAME, PHASE, BUILD
from doorhangers import router as doorhangers_router

app = FastAPI(title=SERVICE_NAME)

@app.get("/diag")
def diag():
    return {
        "service": SERVICE_NAME,
        "phase": PHASE,
        "build": BUILD
    }

@app.get("/db/ping")
def db_ping():
    return {"ok": True}

@app.get("/4over/whoami")
def whoami():
    from fourover_client import FourOverClient
    return FourOverClient().whoami()

app.include_router(doorhangers_router)
