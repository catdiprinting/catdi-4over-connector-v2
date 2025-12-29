# main.py
import os
import traceback
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import init_db, SessionLocal
from fourover_client import FourOverClient


APP_SERVICE = "catdi-4over-connector"
APP_PHASE = "0.7"
APP_BUILD = "catalog-db-enabled"


def _env_presence() -> Dict[str, bool]:
    return {
        "FOUR_OVER_APIKEY": bool(os.getenv("FOUR_OVER_APIKEY")),
        "FOUR_OVER_PRIVATE_KEY": bool(os.getenv("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_BASE_URL": bool(os.getenv("FOUR_OVER_BASE_URL")),
        "DATABASE_URL": bool(os.getenv("DATABASE_URL")),
    }


def _safe_500(e: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc(),
            "env_present": _env_presence(),
        },
    )


app = FastAPI(title=APP_SERVICE)


@app.on_event("startup")
def _startup() -> None:
    # Create tables if they don't exist
    init_db()


@app.get("/")
def root() -> Dict[str, Any]:
    return {"service": APP_SERVICE, "phase": APP_PHASE, "build": APP_BUILD}


@app.get("/version")
def version() -> Dict[str, Any]:
    return {"service": APP_SERVICE, "phase": APP_PHASE, "build": APP_BUILD}


@app.get("/routes")
def routes() -> Dict[str, Any]:
    # Helps confirm what endpoints are actually mounted
    out = []
    for r in app.router.routes:
        methods = sorted(list(getattr(r, "methods", []) or []))
        path = getattr(r, "path", "")
        name = getattr(r, "name", "")
        out.append({"path": path, "methods": methods, "name": name})
    return {"count": len(out), "routes": out}


@app.get("/health")
def health() -> Dict[str, Any]:
    # Basic app + DB health check
    try:
        db_ok = False
        db_err = None
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            db_err = str(e)
        finally:
            db.close()

        return {
            "ok": True,
            "service": APP_SERVICE,
            "phase": APP_PHASE,
            "build": APP_BUILD,
            "env_present": _env_presence(),
            "db_ok": db_ok,
            "db_error": db_err,
        }
    except Exception as e:
        return _safe_500(e)


@app.get("/4over/whoami")
def fourover_whoami() -> Dict[str, Any]:
    try:
        client = FourOverClient()
        resp = client.request("GET", "/whoami")
        return resp
    except Exception as e:
        return _safe_500(e)


@app.post("/admin/sync-products")
def sync_products_smoke() -> Dict[str, Any]:
    """
    For now: a guaranteed-safe endpoint that confirms:
      - the POST route works (no 404)
      - DB is reachable from the web service
      - 4over is reachable via GET /whoami (optional sanity check)

    Next step after this passes: implement actual catalog ingestion + pricing matrix.
    """
    try:
        # --- DB check ---
        db_ok = False
        db_err = None
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            db_err = str(e)
        finally:
            db.close()

        # --- 4over check (non-fatal) ---
        four_ok = False
        four_http = None
        four_err = None
        try:
            client = FourOverClient()
            who = client.request("GET", "/whoami")
            four_ok = bool(who.get("ok"))
            four_http = who.get("http_status")
            if not four_ok:
                four_err = who.get("data")
        except Exception as e:
            four_err = str(e)

        return {
            "ok": True,
            "message": "sync endpoint reached",
            "db_ok": db_ok,
            "db_error": db_err,
            "fourover_ok": four_ok,
            "fourover_http_status": four_http,
            "fourover_error": four_err,
            "env_present": _env_presence(),
        }
    except Exception as e:
        return _safe_500(e)
