# main.py
import os
import traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse

APP_NAME = "catdi-4over-connector"
PHASE = "SAFE_BOOT"
BUILD = "SAFE_BOOT_2025-12-30_2218_FIX_502"

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"

app = FastAPI(title=APP_NAME)

IMPORT_STATUS = {}
NOTES = []


@app.exception_handler(Exception)
async def all_exception_handler(request, exc: Exception):
    if DEBUG_ERRORS:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
                "trace": traceback.format_exc(),
                "path": str(request.url),
            },
        )
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal Server Error"})


@app.get("/health")
def health():
    # This MUST respond fast; never touch DB here.
    return {"ok": True, "service": APP_NAME, "phase": PHASE, "build": BUILD}


@app.get("/diag")
def diag():
    return {
        "service": APP_NAME,
        "phase": PHASE,
        "build": BUILD,
        "imports": IMPORT_STATUS,
        "notes": NOTES,
    }


# -------- Safe imports (do NOT crash app on boot) --------

# db import
try:
    from db import engine, Base  # noqa: F401
    IMPORT_STATUS["db.py"] = {"ok": True, "error": ""}
except Exception as e:
    IMPORT_STATUS["db.py"] = {"ok": False, "error": str(e)}
    NOTES.append("db import failed - app running in SAFE_BOOT without DB")
    engine = None
    Base = None

# models import
try:
    from models import Product, ProductOptionGroup, ProductOptionValue, ProductBasePrice  # noqa: F401
    IMPORT_STATUS["models.py"] = {"ok": True, "error": ""}
except Exception as e:
    IMPORT_STATUS["models.py"] = {"ok": False, "error": str(e)}
    NOTES.append("models import failed - routes depending on models will be disabled")

# Try create_all but NEVER block boot
if engine is not None and Base is not None and IMPORT_STATUS.get("models.py", {}).get("ok"):
    try:
        Base.metadata.create_all(bind=engine)
        NOTES.append("Base.metadata.create_all OK")
    except Exception as e:
        NOTES.append(f"create_all failed (ignored for boot): {e}")

# include doorhangers router safely
try:
    from doorhangers import router as doorhangers_router
    app.include_router(doorhangers_router)
    IMPORT_STATUS["doorhangers.py (router include)"] = {"ok": True, "error": ""}
except Exception as e:
    IMPORT_STATUS["doorhangers.py (router include)"] = {"ok": False, "error": str(e)}
    NOTES.append("doorhangers router failed to include - check error in /diag")
