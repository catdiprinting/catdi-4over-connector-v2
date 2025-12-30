# main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import traceback

from db import engine, Base, db_ping

APP_NAME = "catdi-4over-connector"
PHASE = "SAFE_BOOT"
BUILD = "SAFE_BOOT_2025-12-30_FIX_MODELS_AND_DB_PING"

app = FastAPI(title=APP_NAME)

# Always create tables that exist in metadata
try:
    Base.metadata.create_all(bind=engine)
except Exception:
    # don't crash boot on table create
    pass


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/db/ping")
def db_ping_route():
    db_ping()
    return {"ok": True}


@app.get("/diag")
def diag():
    report = {
        "service": APP_NAME,
        "phase": PHASE,
        "build": BUILD,
        "imports": {},
        "notes": [],
    }

    # db.py always
    try:
        import db as _db  # noqa
        report["imports"]["db.py"] = {"ok": True, "error": ""}
    except Exception as e:
        report["imports"]["db.py"] = {"ok": False, "error": str(e)}

    # models.py
    try:
        from models import Product, ProductOptionGroup, ProductOptionValue, ProductBasePrice  # noqa
        report["imports"]["models.py"] = {"ok": True, "error": ""}
    except Exception as e:
        report["imports"]["models.py"] = {"ok": False, "error": str(e)}
        report["notes"].append("models import failed - routes depending on models will be disabled")

    # doorhangers router
    try:
        from doorhangers import router as doorhangers_router  # noqa
        report["imports"]["doorhangers.py (router include)"] = {"ok": True, "error": ""}
    except Exception as e:
        report["imports"]["doorhangers.py (router include)"] = {"ok": False, "error": str(e)}
        report["notes"].append("doorhangers router failed to include - check error in /diag")

    return report


# Try to include the router on boot (but do NOT crash if it fails)
try:
    from doorhangers import router as doorhangers_router
    app.include_router(doorhangers_router)
except Exception:
    # keep app alive with SAFE_BOOT endpoints
    pass
