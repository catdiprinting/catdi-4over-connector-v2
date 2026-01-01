import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.fourover_client import FourOverClient, FourOverAuthError, FourOverHTTPError, FourOverError

# Load .env only if present locally (Railway does not need .env)
if os.path.exists(".env"):
    load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


app = FastAPI(title="Catdi 4over Connector", version="v2")


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector-v2", "phase": "boot+routes"}


@app.get("/debug/auth")
def debug_auth():
    # Never leak secrets; only presence
    return {
        "FOUR_OVER_BASE_URL": _env_str("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        "FOUR_OVER_APIKEY_present": bool(_env_str("FOUR_OVER_APIKEY")),
        "FOUR_OVER_PRIVATE_KEY_present": bool(_env_str("FOUR_OVER_PRIVATE_KEY")),
        "FOUR_OVER_TIMEOUT": _env_int("FOUR_OVER_TIMEOUT", 30),
    }


def _client() -> FourOverClient:
    # Uses env vars; also supports legacy "public_key"/"timeout" if you ever pass them
    return FourOverClient(
        base_url=_env_str("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        apikey=_env_str("FOUR_OVER_APIKEY"),
        private_key=_env_str("FOUR_OVER_PRIVATE_KEY"),
        timeout_seconds=_env_int("FOUR_OVER_TIMEOUT", 30),
    )


@app.get("/4over/whoami")
def whoami():
    try:
        data = _client().whoami()
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": "auth_error", "detail": str(e)})
    except FourOverHTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "upstream_error", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "client_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})
