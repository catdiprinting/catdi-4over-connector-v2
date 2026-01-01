import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.fourover_client import FourOverClient, FourOverAuthError, FourOverHTTPError, FourOverError

# Load .env locally (Railway uses env vars directly; this won't hurt)
load_dotenv()

app = FastAPI(title="Catdi 4over Connector", version="v2")


@app.get("/ping")
def ping():
    return {"ok": True, "service": "catdi-4over-connector-v2"}


@app.get("/debug/auth")
def debug_auth():
    """Confirms env vars exist (never returns secrets)."""
    base_url = os.getenv("FOUR_OVER_BASE_URL", "").strip()
    apikey_present = bool((os.getenv("FOUR_OVER_APIKEY") or "").strip())
    private_present = bool((os.getenv("FOUR_OVER_PRIVATE_KEY") or "").strip())
    timeout = os.getenv("FOUR_OVER_TIMEOUT", "30").strip()

    return {
        "base_url_present": bool(base_url),
        "base_url_value": base_url if base_url else None,
        "FOUR_OVER_APIKEY_present": apikey_present,
        "FOUR_OVER_PRIVATE_KEY_present": private_present,
        "FOUR_OVER_TIMEOUT": timeout,
    }


def _client() -> FourOverClient:
    # preferred names
    return FourOverClient(
        base_url=os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"),
        apikey=os.getenv("FOUR_OVER_APIKEY", ""),
        private_key=os.getenv("FOUR_OVER_PRIVATE_KEY", ""),
        timeout_seconds=int(os.getenv("FOUR_OVER_TIMEOUT", "30")),
    )


@app.get("/4over/whoami")
def whoami():
    c = _client()
    try:
        data = c.whoami()
        return {"ok": True, "data": data}
    except FourOverAuthError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": "auth_error", "detail": str(e)})
    except FourOverHTTPError as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "upstream_error", "detail": str(e)})
    except FourOverError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "client_error", "detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "server_error", "detail": str(e)})
