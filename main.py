# main.py
from fastapi import FastAPI
from sqlalchemy import text

from db import engine, Base
import db as db_module

app = FastAPI(title="catdi-4over-connector", version="SAFE_AND_STABLE")

# Create tables (safe to call on boot)
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/db/ping")
def db_ping():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/diag")
def diag():
    """
    SAFE_BOOT import diagnostics so app doesn't hard-crash if a module breaks.
    """
    results = {"service": "catdi-4over-connector", "phase": "SAFE_BOOT", "build": "SAFE_BOOT", "imports": {}, "notes": []}

    def _try(name, fn):
        try:
            fn()
            results["imports"][name] = {"ok": True, "error": ""}
        except Exception as e:
            results["imports"][name] = {"ok": False, "error": str(e)}
            results["notes"].append(f"{name} import failed - routes depending on it will be disabled")

    _try("db.py", lambda: __import__("db"))
    _try("models.py", lambda: __import__("models"))
    _try("fourover_client.py", lambda: __import__("fourover_client"))

    # Try include router(s)
    try:
        from doorhangers import router as doorhangers_router
        app.include_router(doorhangers_router)
        results["imports"]["doorhangers.py (router include)"] = {"ok": True, "error": ""}
    except Exception as e:
        results["imports"]["doorhangers.py (router include)"] = {"ok": False, "error": str(e)}
        results["notes"].append("doorhangers router failed to include - check error in /diag")

    return results


# Include routers normally (non-diag path). If they fail, /diag still works.
try:
    from doorhangers import router as doorhangers_router
    app.include_router(doorhangers_router)
except Exception:
    pass
