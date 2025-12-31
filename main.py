# main.py
from fastapi import FastAPI
from db import Base, engine
import importlib

app = FastAPI(title="catdi-4over-connector", version="SAFE_BOOT")

# Ensure tables exist
Base.metadata.create_all(bind=engine)

@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "DOORHANGERS_PRICING_TESTER"}

@app.get("/db/ping")
def db_ping():
    return {"ok": True}

@app.get("/diag")
def diag():
    checks = {}
    notes = []

    def try_import(label: str, mod: str):
        try:
            importlib.import_module(mod)
            checks[label] = {"ok": True, "error": ""}
            return True
        except Exception as e:
            checks[label] = {"ok": False, "error": str(e)}
            return False

    try_import("db.py", "db")
    models_ok = try_import("models.py", "models")
    client_ok = try_import("fourover_client.py", "fourover_client")
    door_ok = try_import("doorhangers.py (router include)", "doorhangers")

    if not models_ok:
        notes.append("models import failed - routes depending on models will be disabled")
    if not door_ok:
        notes.append("doorhangers router failed to include - check error in /diag")

    return {
        "service": "catdi-4over-connector",
        "phase": "SAFE_BOOT",
        "build": "SAFE_BOOT",
        "imports": checks,
        "notes": notes,
    }

# Include routers (safe)
from doorhangers import router as doorhangers_router
app.include_router(doorhangers_router)
