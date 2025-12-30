from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os
import traceback

APP_NAME = "catdi-4over-connector"
PHASE = "SAFE_BOOT"
BUILD = "SAFE_BOOT_2025-12-30"

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"

app = FastAPI(title=APP_NAME)

BOOT_STATUS = {
    "service": APP_NAME,
    "phase": PHASE,
    "build": BUILD,
    "imports": {},
    "notes": [],
}

def _record_import(name: str, ok: bool, err: str = ""):
    BOOT_STATUS["imports"][name] = {"ok": ok, "error": err[:2000] if err else ""}

def _try_import(name: str, importer):
    try:
        importer()
        _record_import(name, True, "")
        return True
    except Exception as e:
        _record_import(name, False, f"{repr(e)}\n{traceback.format_exc()}")
        return False

@app.get("/")
def root():
    return {"service": APP_NAME, "phase": PHASE, "build": BUILD}

@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}

@app.get("/diag")
def diag():
    """
    If Railway is up, this tells us exactly which import(s) are failing at boot time.
    """
    return BOOT_STATUS

# ---- Try importing modules, but NEVER crash the app ----

def _import_db():
    import db  # noqa

def _import_models():
    import models  # noqa

def _import_client():
    import fourover_client  # noqa

def _import_pricing_router():
    from pricing_tester import router as pricing_router  # noqa
    app.include_router(pricing_router)

# Attempt imports (safe)
_try_import("db.py", _import_db)
_try_import("models.py", _import_models)
_try_import("fourover_client.py", _import_client)
_try_import("pricing_tester.py (router include)", _import_pricing_router)

# OPTIONAL: add your original routes ONLY if you want, later.
# Right now we keep SAFE BOOT minimal so Railway stops crashing.
