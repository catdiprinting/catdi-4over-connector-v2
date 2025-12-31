# main.py
from fastapi import FastAPI
from db import Base, engine
import importlib
import os

app = FastAPI(title="catdi-4over-connector", version="SAFE_BOOT")

Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector", "phase": "SAFE_BOOT"}


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
    if not client_ok:
        notes.append("fourover_client import failed - 4over calls will fail")
    if not door_ok:
        notes.append("doorhangers router failed to include - check error in /diag")

    env = {
        "FOUR_OVER_BASE_URL": os.getenv("FOUR_OVER_BASE_URL"),
        "FOUR_OVER_APIKEY_present": bool((os.getenv("FOUR_OVER_APIKEY") or "").strip()),
        "FOUR_OVER_PRIVATE_KEY_present": bool((os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip()),
    }

    return {
        "service": "catdi-4over-connector",
        "phase": "SAFE_BOOT",
        "build": "SAFE_BOOT",
        "imports": checks,
        "env": env,
        "notes": notes,
    }


# --- Routers ---
from doorhangers import router as doorhangers_router
app.include_router(doorhangers_router)


# --- Minimal 4over sanity route (so you can test auth quickly) ---
from fourover_client import get_raw as four_get_raw
import requests

@app.get("/4over/whoami")
def whoami():
    resp = four_get_raw("/whoami")
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"_raw_text": (resp.text or "")[:3000]}
        raise Exception({"upstream_status": resp.status_code, "upstream_body": body})
    try:
        return resp.json()
    except Exception:
        return {"_raw_text": (resp.text or "")[:3000]}
