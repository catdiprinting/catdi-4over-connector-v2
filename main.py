from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from db import SessionLocal, init_db
from models import BasePriceCache, BasePriceRow
from fourover_client import FourOverClient, FourOverError
import os

from config import FOUR_OVER_BASE_URL, FOUR_OVER_APIKEY, FOUR_OVER_PRIVATE_KEY

app = FastAPI(title="Catdi 4over Connector", version="0.9")

fourover = FourOverClient()


def safe_error(payload: dict, status_code: int = 500):
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/version")
def version():
    return {"service": "catdi-4over-connector", "version": "0.9", "time": datetime.utcnow().isoformat()}


@app.get("/_router_error")
def router_error():
    # This is just a friendly “if something fails at import time”
    return {"ok": True}


@app.get("/db/ping")
def db_ping():
    try:
        with SessionLocal() as db:
            db.execute(select(1))
        return {"ok": True}
    except Exception as e:
        return safe_error({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.post("/db/init")
def db_init():
    try:
        init_db()
        return {"ok": True, "tables": ["baseprice_cache", "baseprice_rows"]}
    except Exception as e:
        return safe_error({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/debug/auth")
def debug_auth():
    try:
        return {
            "ok": True,
            "base_url": FOUR_OVER_BASE_URL,
            "apikey_present": bool(FOUR_OVER_APIKEY),
            "private_key_present": bool(FOUR_OVER_PRIVATE_KEY),
            "private_key_len": len((FOUR_OVER_PRIVATE_KEY or "")),
            "private_key_stripped_len": len((FOUR_OVER_PRIVATE_KEY or "").strip()),
            "private_key_endswith_newline": (FOUR_OVER_PRIVATE_KEY or "").endswith("\n"),
            "note": "Signature is canonical(path+query) HMAC-SHA256 with private key",
        }
    except Exception as e:
        return safe_error({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/debug/fingerprint")
def debug_fingerprint():
    """Single source of truth for "what code is live" + "what schema is live"."""
    try:
        # Build/version metadata
        build_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT") or "unknown"
        # Minimal schema introspection
        schema = {"ok": True, "tables": {}, "schema_version": None}
        with SessionLocal() as db:
            try:
                # PostgreSQL: query information_schema for columns
                for table in ["baseprice_cache", "baseprice_rows"]:
                    rows = db.execute(
                        select(1)
                    )
                # Use SQLAlchemy inspector (no extra dependency)
                from sqlalchemy import inspect

                insp = inspect(db.get_bind())
                for table in ["baseprice_cache", "baseprice_rows"]:
                    if table in insp.get_table_names():
                        schema["tables"][table] = [c["name"] for c in insp.get_columns(table)]
                    else:
                        schema["tables"][table] = None
            except Exception as se:
                schema = {"ok": False, "error": str(se)}

        return {
            "ok": True,
            "service": "catdi-4over-connector",
            "version": "0.9",
            "build": build_sha,
            "time": datetime.utcnow().isoformat(),
            "auth": {
                "base_url": FOUR_OVER_BASE_URL,
                "apikey_present": bool(FOUR_OVER_APIKEY),
                "private_key_present": bool(FOUR_OVER_PRIVATE_KEY),
            },
            "db": schema,
        }
    except Exception as e:
        return safe_error({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/debug/sign")
def debug_sign(product_uuid: str = Query(None)):
    """Return the exact canonical strings/signatures we would send.

    This lets you compare failures across endpoints without guessing.
    """
    try:
        from fourover_client import _canonical_query, signature_for_canonical

        tests = []

        # whoami
        canonical = f"/whoami?{_canonical_query({'apikey': FOUR_OVER_APIKEY})}"
        tests.append({"name": "whoami", "canonical": canonical, "signature": signature_for_canonical(canonical)})

        if product_uuid:
            for path in [
                f"/printproducts/products/{product_uuid}/baseprices",
                f"/printproducts/products/{product_uuid}/optiongroups",
            ]:
                c = f"{path}?{_canonical_query({'apikey': FOUR_OVER_APIKEY})}"
                tests.append({"name": path, "canonical": c, "signature": signature_for_canonical(c)})

        return {"ok": True, "tests": tests}
    except Exception as e:
        return safe_error({"ok": False, "error": str(e), "trace": traceback.format_exc()}, status_code=500)


# -----------------------------
# 4over endpoints
# -----------------------------
@app.get("/4over/whoami")
def whoami():
    try:
        return fourover.whoami()
    except FourOverError as e:
        return safe_error(
            {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical},
            status_code=e.status,
        )
    except Exception as e:
        return safe_error({"error": "unexpected", "message": str(e), "trace": traceback.format_exc()}, status_code=500)


# -----------------------------
# Cache endpoints
# -----------------------------
@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    try:
        with SessionLocal() as db:
            # show most recent updated rows
            stmt = select(BasePriceCache).order_by(BasePriceCache.updated_at.desc()).limit(limit)
            rows = db.execute(stmt).scalars().all()
            return {
                "ok": True,
                "count": len(rows),
                "entities": [
                    {
                        "id": r.id,
                        "product_uuid": r.product_uuid,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return safe_error({"error": "cache_list_failed", "message": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/cache/baseprices/{product_uuid}")
def cache_baseprices_by_product(product_uuid: str):
    try:
        with SessionLocal() as db:
            stmt = select(BasePriceCache).where(BasePriceCache.product_uuid == product_uuid).limit(1)
            row = db.execute(stmt).scalars().first()
            if not row:
                raise HTTPException(status_code=404, detail={"error": "not_found", "product_uuid": product_uuid})
            return {"ok": True, "id": row.id, "product_uuid": row.product_uuid, "updated_at": row.updated_at, "payload": row.payload}
    except HTTPException:
        raise
    except Exception as e:
        return safe_error({"error": "cache_fetch_failed", "message": str(e), "trace": traceback.format_exc()}, status_code=500)


# -----------------------------
# Doorhangers endpoints (baseprices + import + options + quote)
# -----------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhangers_baseprices(product_uuid: str):
    try:
        return fourover.product_baseprices(product_uuid)
    except FourOverError as e:
        return safe_error(
            {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical},
            status_code=e.status,
        )


def _parse_price(entity: dict) -> float:
    # 4over fields vary by endpoint/version; try common ones safely
    candidates = [
        entity.get("base_price"),
        entity.get("price"),
        entity.get("product_price"),
        entity.get("total_price"),
    ]
    for c in candidates:
        if c is None:
            continue
        try:
            return float(c)
        except Exception:
            pass
    return 0.0


def _to_text(v: Any) -> str:
    return "" if v is None else str(v)


@app.post("/doorhangers/import/{product_uuid}")
def import_doorhanger_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over.
    - UPSERT cache row (1 row per product_uuid)
    - REPLACE normalized baseprice_rows for product_uuid (delete then insert)
    """
    try:
        data = fourover.product_baseprices(product_uuid)
        entities = data.get("entities", [])

        if not isinstance(entities, list) or len(entities) == 0:
            return safe_error({"error": "no_baseprices_returned", "product_uuid": product_uuid, "raw": data}, status_code=400)

        with SessionLocal() as db:
            # 1) UPSERT cache
            existing = db.execute(
                select(BasePriceCache).where(BasePriceCache.product_uuid == product_uuid).limit(1)
            ).scalars().first()

            if existing:
                existing.payload = data
                existing.updated_at = datetime.utcnow()
            else:
                existing = BasePriceCache(product_uuid=product_uuid, payload=data, updated_at=datetime.utcnow())
                db.add(existing)

            # 2) Replace normalized rows
            db.execute(delete(BasePriceRow).where(BasePriceRow.product_uuid == product_uuid))

            rows = []
            for e in entities:
                runsize_uuid = _to_text(e.get("runsize_uuid") or e.get("runsizeid") or e.get("runsize_id"))
                colorspec_uuid = _to_text(e.get("colorspec_uuid") or e.get("colorspecid") or e.get("colorspec_id"))
                runsize = _to_text(e.get("runsize"))
                colorspec = _to_text(e.get("colorspec"))
                can_group_ship = bool(e.get("can_group_ship", False))
                base_price = _parse_price(e)

                # Skip clearly invalid rows
                if not runsize_uuid or not colorspec_uuid or not runsize or not colorspec:
                    continue

                rows.append(
                    BasePriceRow(
                        product_uuid=product_uuid,
                        runsize_uuid=runsize_uuid,
                        runsize=runsize,
                        colorspec_uuid=colorspec_uuid,
                        colorspec=colorspec,
                        base_price=base_price,
                        can_group_ship=can_group_ship,
                        raw=e,
                    )
                )

            if not rows:
                return safe_error(
                    {"error": "no_valid_rows_parsed", "product_uuid": product_uuid, "hint": "Baseprices payload did not contain expected fields"},
                    status_code=400,
                )

            db.add_all(rows)
            db.commit()

            return {"ok": True, "product_uuid": product_uuid, "cache_updated_at": existing.updated_at.isoformat(), "rows_inserted": len(rows)}

    except FourOverError as e:
        return safe_error(
            {"error": "4over_request_failed", "status": e.status, "url": e.url, "body": e.body, "canonical": e.canonical},
            status_code=e.status,
        )
    except SQLAlchemyError as e:
        return safe_error({"error": "db_error", "message": str(e)}, status_code=500)
    except Exception as e:
        return safe_error({"error": "unexpected", "message": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    Pull optiongroups from 4over (if auth works) OR fall back to cache-derived runsizes/colorspecs.
    """
    try:
        # Attempt live optiongroups first
        try:
            og = fourover.product_optiongroups(product_uuid)
            return {"ok": True, "product_uuid": product_uuid, "source": "4over_optiongroups", "optiongroups": og}
        except FourOverError:
            pass

        # Fallback: derive from normalized rows
        with SessionLocal() as db:
            stmt = select(BasePriceRow).where(BasePriceRow.product_uuid == product_uuid)
            rows = db.execute(stmt).scalars().all()

        runsizes = sorted({r.runsize for r in rows})
        colorspecs = sorted({r.colorspec for r in rows})

        return {"ok": True, "product_uuid": product_uuid, "source": "db_baseprice_rows", "runsizes": runsizes, "colorspecs": colorspecs}

    except Exception as e:
        return safe_error({"error": "options_failed", "message": str(e), "trace": traceback.format_exc()}, status_code=500)


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: str | None = Query(None),
    colorspec: str | None = Query(None),
    runsize_uuid: str | None = Query(None),
    colorspec_uuid: str | None = Query(None),
    markup_pct: float = Query(25.0),
    auto_import: bool = Query(False),
):
    """
    Quote using normalized DB rows.
    - If missing rows and auto_import=true, import first.
    """
    try:
        def _load_row():
            with SessionLocal() as db:
                q = select(BasePriceRow).where(BasePriceRow.product_uuid == product_uuid)

                if runsize_uuid:
                    q = q.where(BasePriceRow.runsize_uuid == runsize_uuid)
                elif runsize:
                    q = q.where(BasePriceRow.runsize == runsize)

                if colorspec_uuid:
                    q = q.where(BasePriceRow.colorspec_uuid == colorspec_uuid)
                elif colorspec:
                    q = q.where(BasePriceRow.colorspec == colorspec)

                return db.execute(q.limit(1)).scalars().first()

        row = _load_row()

        if not row and auto_import:
            import_doorhanger_baseprices(product_uuid)
            row = _load_row()

        if not row:
            raise HTTPException(status_code=404, detail="No matching baseprice row for selected options")

        base = float(row.base_price or 0.0)
        m = float(markup_pct or 0.0) / 100.0
        sell = round(base * (1.0 + m), 4)

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "selected": {
                "runsize": row.runsize,
                "runsize_uuid": row.runsize_uuid,
                "colorspec": row.colorspec,
                "colorspec_uuid": row.colorspec_uuid,
            },
            "pricing": {
                "base_price": base,
                "markup_pct": float(markup_pct),
                "sell_price": sell,
            },
            "meta": {"can_group_ship": row.can_group_ship},
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        return safe_error({"error": "quote_failed", "message": str(e), "trace": traceback.format_exc()}, status_code=500)
