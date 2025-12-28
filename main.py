from fastapi import FastAPI
from typing import Dict, Any
import os
import psycopg2

from fourover_client import FourOverClient

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------

app = FastAPI(
    title="Catdi 4over Connector",
    version="0.6",
)

# -----------------------------------------------------------------------------
# Root / Health
# -----------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "catdi-4over-connector",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {
        "service": "catdi-4over-connector",
        "phase": "0.6",
        "build": "4over-ping-enabled",
    }


@app.get("/fingerprint")
def fingerprint():
    return {
        "fingerprint": "ROOT_MAIN_PY_V1",
        "file": "/app/main.py",
    }

# -----------------------------------------------------------------------------
# Database (lazy / safe)
# -----------------------------------------------------------------------------

@app.get("/db-check")
def db_check() -> Dict[str, Any]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {"db": "missing DATABASE_URL"}

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {
            "db": "error",
            "error": str(e),
        }

# -----------------------------------------------------------------------------
# 4over – AUTH TEST
# -----------------------------------------------------------------------------

@app.get("/4over/whoami")
def fourover_whoami():
    """
    Ping 4over authentication.
    This MUST include apikey + signature in QUERY (GET request).
    """
    client = FourOverClient()
    return client.request("GET", "/whoami")

# -----------------------------------------------------------------------------
# Future endpoints will live below (locked for now)
# -----------------------------------------------------------------------------
# /4over/categories
# /4over/products
# /explorer/business-cards
# /pricing/preview
# -----------------------------------------------------------------------------
