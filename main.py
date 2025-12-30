# main.py
from fastapi import FastAPI
from doorhangers import router as doorhangers_router
from db import engine, Base

app = FastAPI(title="Catdi 4over Connector")

# Create tables safely
Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "catdi-4over-connector",
        "phase": "DOORHANGERS_PRICING_TESTER",
        "build": "STABLE_ROUTER_SPLIT"
    }

# Include Doorhangers router
app.include_router(doorhangers_router)
