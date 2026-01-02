from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from app.db import get_db, init_db
from app.fourover_client import FourOverClient
from app import models

app = FastAPI(title="catdi-4over-connector", version="1.0")

client = FourOverClient()


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "service": "catdi-4over-connector"}


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        return {"ok": True, "db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/auth")
def debug_auth():
    """
    This endpoint lets you confirm the *exact* auth behavior without leaking secrets.
    """
    from app.config import (
        FOUR_OVER_BASE_URL,
        FOUR_OVER_API_PREFIX,
        FOUR_OVER_TIMEOUT,
        FOUR_OVER_APIKEY,
        FOUR_OVER_PRIVATE_KEY,
    )

    apikey = (FOUR_OVER_APIKEY or "").strip()
    pkey = (FOUR_OVER_PRIVATE_KEY or "").strip()

    # show only safe fingerprints
    def safe_edge(s: str, n: int = 3) -> str:
        if not s:
            return ""
        if len(s) <= n * 2:
            return s
        return f"{s[:n]}...{s[-n:]}"

    # compute method signatures (safe to show; derived)
    try:
        sig_get = client.signature_for_method("GET")
        sig_post = client.signature_for_method("POST")
    except Exception:
        sig_get = None
        sig_post = None

    return {
        "base_url": (FOUR_OVER_BASE_URL or "").rstrip("/"),
        "api_prefix": (FOUR_OVER_API_PREFIX or "").strip("/"),
        "timeout": str(FOUR_OVER_TIMEOUT),
        "apikey_present": bool(apikey),
        "private_key_present": bool(pkey),
        "apikey_edge": safe_edge(apikey, 3),
        "private_key_len": len(pkey),
        "sig_GET_edge": safe_edge(sig_get or "", 6),
        "sig_POST_edge": safe_edge(sig_post or "", 6),
        "whoami_url_example": f"{(FOUR_OVER_BASE_URL or '').rstrip('/')}/whoami?apikey={apikey}&signature=<sig_for_GET>",
        "note": "GET uses query auth; POST uses Authorization header: API apikey:signature",
    }


# ----------------------------
# 4over passthrough endpoints
# ----------------------------

@app.get("/4over/whoami")
def whoami():
    r = client.get("/whoami")
    try:
        data = r.json()
    except E
