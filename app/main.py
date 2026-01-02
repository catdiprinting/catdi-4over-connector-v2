from fastapi import FastAPI, HTTPException
from app.fourover_client import FourOverClient

app = FastAPI(title="catdi-4over-connector")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/debug/auth")
def debug_auth():
    """
    This must work even before 4over calls.
    """
    try:
        client = FourOverClient()
        sig = client._signature("GET")
        return {
            "ok": True,
            "apikey_present": True,
            "private_key_present": True,
            "sig_sample": sig[:10] + "...",
            "base_test_url": "https://web-production-009a.up.railway.app/4over/whoami",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/4over/whoami")
def whoami():
    client = FourOverClient()
    r = client.get("/whoami")

    try:
        return {
            "ok": r.ok,
            "status": r.status_code,
            "data": r.json(),
        }
    except Exception:
        return {
            "ok": r.ok,
            "status": r.status_code,
            "raw": r.text,
        }
