# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami, build_signed_url
from db import ensure_schema, insert_baseprice_cache, list_baseprice_cache, latest_baseprice_cache

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "ROOT_MAIN_PY_V9_SAFE_DEBUG_ENDPOINT",
}
from urllib.parse import urlencode
import hashlib, hmac, time, requests
from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY

@app.get("/4over/debug/auth-matrix")
def auth_matrix():
    """
    Tries multiple signature algorithms against /whoami and reports results.
    Does NOT expose the private key.
    """
    if not FOUR_OVER_APIKEY or not FOUR_OVER_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="Missing FOUR_OVER_APIKEY or FOUR_OVER_PRIVATE_KEY")

    # IMPORTANT: strip whitespace/newlines
    pk_raw = FOUR_OVER_PRIVATE_KEY.strip()

    # build key bytes in two ways: raw + hex-decoded (some providers do this)
    keys = []
    keys.append(("raw_utf8", pk_raw.encode("utf-8")))

    # hex attempt (only if it looks hex)
    hex_chars = set("0123456789abcdefABCDEF")
    if len(pk_raw) % 2 == 0 and all(c in hex_chars for c in pk_raw):
        try:
            keys.append(("hex_bytes", bytes.fromhex(pk_raw)))
        except Exception:
            pass

    ts = int(time.time())
    params = {"apikey": FOUR_OVER_APIKEY, "timestamp": ts}
    canonical = f"/whoami?{urlencode(params)}"

    def mkurl(sig: str) -> str:
        q = dict(params)
        q["signature"] = sig
        return f"{FOUR_OVER_BASE_URL}/whoami?{urlencode(q)}"

    results = []

    for key_name, key_bytes in keys:
        for algo_name, fn in [
            ("hmac_sha256", lambda k, m: hmac.new(k, m.encode("utf-8"), hashlib.sha256).hexdigest()),
            ("hmac_sha1",   lambda k, m: hmac.new(k, m.encode("utf-8"), hashlib.sha1).hexdigest()),
            ("plain_sha256",lambda k, m: hashlib.sha256(k + m.encode("utf-8")).hexdigest()),
            ("plain_sha1",  lambda k, m: hashlib.sha1(k + m.encode("utf-8")).hexdigest()),
        ]:
            sig = fn(key_bytes, canonical)
            url = mkurl(sig)
            try:
                r = requests.get(url, timeout=20)
                results.append({
                    "key": key_name,
                    "algo": algo_name,
                    "status": r.status_code,
                    "ok": r.status_code < 400,
                    "canonical": canonical,
                    "url": url,
                    "body_snip": r.text[:200],
                })
            except Exception as e:
                results.append({
                    "key": key_name,
                    "algo": algo_name,
                    "status": None,
                    "ok": False,
                    "canonical": canonical,
                    "url": url,
                    "error": str(e),
                })

    return {"results": results}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    return {"ok": True}


@app.post("/db/init")
def db_init():
    try:
        ensure_schema()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB init failed: {e}")


# ---- 4over Debug (SAFE) ----
@app.get("/4over/debug/whoami")
def debug_whoami():
    try:
        signed = build_signed_url("/whoami")
        return {
            "canonical": signed["canonical"],
            "url": signed["url"],
            "signature": signed["signature"],
        }
    except FourOverError as e:
        # If env vars are missing, you'll see it here instead of a hard 500
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "error": "4over debug failed",
                    "status": e.status,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        # Any import/name errors show up here cleanly
        return JSONResponse(
            status_code=500,
            content={"detail": {"error": "debug endpoint crashed", "message": str(e)}},
        )


@app.get("/4over/whoami")
def four_over_whoami():
    try:
        return whoami()
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return product_baseprices(product_uuid)
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    try:
        ensure_schema()
        payload = product_baseprices(product_uuid)
        cache_id = insert_baseprice_cache(product_uuid, payload)
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over request failed",
                    "status": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": e.canonical,
                }
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "db error", "message": str(e)},
        )


@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        ensure_schema()
        return {"entities": list_baseprice_cache(limit=limit)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "cache list failed", "message": str(e)},
        )


@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    try:
        ensure_schema()
        row = latest_baseprice_cache(product_uuid)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "cache fetch failed", "message": str(e)},
        )
