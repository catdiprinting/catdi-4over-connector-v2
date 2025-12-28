from fastapi import FastAPI
from typing import Dict, Any
import os

app = FastAPI(title="Catdi 4over Connector", version="0.6")

@app.get("/")
def root():
    return {"service": "catdi-4over-connector", "status": "running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "phase": "0.6", "build": "4over-ping-enabled"}

@app.get("/fingerprint")
def fingerprint():
    return {"fingerprint": "ROOT_MAIN_PY_V1", "file": "/app/main.py"}

# -------------------------
# DB CHECK (lazy import)
# -------------------------
@app.get("/db-check")
def db_check() -> Dict[str, Any]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {"db": "missing DATABASE_URL"}

    try:
        import psycopg2  # lazy import so missing psycopg2 won't crash app boot
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "error": str(e)}

# -------------------------
# 4OVER WHOAMI (safe import)
# -------------------------
@app.get("/4over/whoami")
def fourover_whoami():
    try:
        from fourover_client import FourOverClient  # safe import
    except Exception as e:
        return {
            "http_status": 500,
            "ok": False,
            "data": {"message": "Failed to import FourOverClient. Check fourover_client.py exists at root."},
            "debug": {"import_error": str(e)},
        }

    try:
        client = FourOverClient()
        return client.request("GET", "/whoami")
    except Exception as e:
        return {
            "http_status": 500,
            "ok": False,
            "data": {"message": "Exception during 4over request"},
            "debug": {"error": str(e)},
        }
