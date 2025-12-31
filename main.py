# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, product_baseprices, whoami

APP_VERSION = {
    "service": "catdi-4over-connector",
    "phase": "0.9",
    "build": "AUTH_FIRST_METHOD_SIGNATURE_V1",
}

app = FastAPI(title="Catdi 4over Connector", version="0.9")


@app.get("/version")
def version():
    return APP_VERSION


@app.get("/ping")
def ping():
    return {"ok": True}


def _four_over_error_response(e: FourOverError):
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


@app.get("/4over/whoami")
def four_over_whoami(key_mode: str = Query("hexdigest", pattern="^(hexdigest|digest|hexbytes)$")):
    """
    key_mode:
      - hexdigest: matches 4over doc example literally
      - digest / hexbytes: alternates in case 4over expects bytes-style key
    """
    try:
        return whoami(key_mode=key_mode)
    except FourOverError as e:
        return _four_over_error_response(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "unexpected", "message": str(e)})


@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(
    product_uuid: str,
    key_mode: str = Query("hexdigest", pattern="^(hexdigest|digest|hexbytes)$"),
):
    try:
        return product_baseprices(product_uuid, key_mode=key_mode)
    except FourOverError as e:
        return _four_over_error_response(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "unexpected", "message": str(e)})


@app.get("/4over/debug/auth-matrix")
def auth_matrix():
    """
    Calls /whoami 3 ways and reports:
      - which key derivation works (if any)
      - status codes + short body snippet
    This endpoint must NEVER crash the app.
    """
    results = []
    for mode in ["hexdigest", "digest", "hexbytes"]:
        try:
            data = whoami(key_mode=mode)
            results.append({"key_mode": mode, "ok": True, "status": 200, "data": data})
        except FourOverError as e:
            snippet = (e.body or "")[:200]
            results.append(
                {
                    "key_mode": mode,
                    "ok": False,
                    "status": e.status,
                    "url": e.url,
                    "canonical": e.canonical,
                    "body_snippet": snippet,
                }
            )
        except Exception as e:
            results.append({"key_mode": mode, "ok": False, "status": "exception", "error": str(e)})

    return {"results": results}
