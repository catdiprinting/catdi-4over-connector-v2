from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError

import fourover_client as fourover
from fourover_client import FourOverError

from db import SessionLocal, engine
from models import Base, BasePriceCache


SERVICE_NAME = "catdi-4over-connector"
PHASE = "0.9"
BUILD = "ROOT_MAIN_PY_V6_QUOTES_FROM_CACHE"


app = FastAPI(title=SERVICE_NAME, version=PHASE)


# -----------------------------
# Helpers
# -----------------------------
def safe_error(detail: dict, status_code: int = 500):
    """
    Return consistent error payloads (prevents Railway 502 crash loops).
    """
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _norm(s: Any) -> str:
    return str(s or "").strip()


def _norm_colorspec(s: Any) -> str:
    # Normalize "4/4", "4 / 4", "4/0", etc.
    v = _norm(s).replace(" ", "")
    return v.upper()


def _as_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _get_latest_cache(db, product_uuid: str) -> Optional[BasePriceCache]:
    stmt = (
        select(BasePriceCache)
        .where(BasePriceCache.product_uuid == product_uuid)
        .order_by(desc(BasePriceCache.id))
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _extract_entities(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ents = payload.get("entities", [])
    return ents if isinstance(ents, list) else []


def _entity_runsize_label(e: Dict[str, Any]) -> str:
    # Try a few likely shapes
    if "runsize" in e:
        return _norm(e.get("runsize"))
    if isinstance(e.get("runsize_option"), dict):
        return _norm(e["runsize_option"].get("option_name") or e["runsize_option"].get("name"))
    if isinstance(e.get("runsize_data"), dict):
        return _norm(e["runsize_data"].get("name"))
    return _norm(e.get("runsize_name"))


def _entity_runsize_uuid(e: Dict[str, Any]) -> str:
    if "runsize_uuid" in e:
        return _norm(e.get("runsize_uuid"))
    if isinstance(e.get("runsize_option"), dict):
        return _norm(e["runsize_option"].get("option_uuid") or e["runsize_option"].get("uuid"))
    if isinstance(e.get("runsize_data"), dict):
        return _norm(e["runsize_data"].get("uuid"))
    return _norm(e.get("runsize_option_uuid"))


def _entity_colorspec_label(e: Dict[str, Any]) -> str:
    if "colorspec" in e:
        return _norm(e.get("colorspec"))
    if isinstance(e.get("colorspec_option"), dict):
        return _norm(e["colorspec_option"].get("option_name") or e["colorspec_option"].get("name"))
    if isinstance(e.get("colorspec_data"), dict):
        return _norm(e["colorspec_data"].get("name"))
    return _norm(e.get("colorspec_name"))


def _entity_colorspec_uuid(e: Dict[str, Any]) -> str:
    if "colorspec_uuid" in e:
        return _norm(e.get("colorspec_uuid"))
    if isinstance(e.get("colorspec_option"), dict):
        return _norm(e["colorspec_option"].get("option_uuid") or e["colorspec_option"].get("uuid"))
    if isinstance(e.get("colorspec_data"), dict):
        return _norm(e["colorspec_data"].get("uuid"))
    return _norm(e.get("colorspec_option_uuid"))


def _entity_turnaround_label(e: Dict[str, Any]) -> str:
    # Sometimes "turnaround_time" or "turnaroundtime" etc.
    for k in ["turnaroundtime", "turnaround_time", "turnaround", "turnaroundtime_name", "turnaround_name"]:
        if k in e and _norm(e.get(k)):
            return _norm(e.get(k))
    if isinstance(e.get("turnaroundtime_option"), dict):
        return _norm(e["turnaroundtime_option"].get("option_name") or e["turnaroundtime_option"].get("name"))
    if isinstance(e.get("turnaroundtime_data"), dict):
        return _norm(e["turnaroundtime_data"].get("name"))
    return ""


def _entity_turnaround_uuid(e: Dict[str, Any]) -> str:
    for k in ["turnaroundtime_uuid", "turnaround_uuid", "turnaroundtime_option_uuid"]:
        if k in e and _norm(e.get(k)):
            return _norm(e.get(k))
    if isinstance(e.get("turnaroundtime_option"), dict):
        return _norm(e["turnaroundtime_option"].get("option_uuid") or e["turnaroundtime_option"].get("uuid"))
    if isinstance(e.get("turnaroundtime_data"), dict):
        return _norm(e["turnaroundtime_data"].get("uuid"))
    return ""


def _entity_price(e: Dict[str, Any]) -> Optional[float]:
    """
    Baseprices payloads vary; be defensive.
    """
    for k in ["base_price", "price", "total_price", "baseprice"]:
        if k in e and e.get(k) is not None:
            try:
                return float(e.get(k))
            except Exception:
                pass
    # Sometimes nested
    if isinstance(e.get("prices"), dict):
        for k in ["base_price", "price", "total_price"]:
            if k in e["prices"] and e["prices"][k] is not None:
                try:
                    return float(e["prices"][k])
                except Exception:
                    pass
    return None


def _unique_options(entities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    """
    Build unique lists (label + uuid) for runsize/colorspec/turnaround from cached entities.
    """
    run_map: Dict[str, str] = {}
    col_map: Dict[str, str] = {}
    ta_map: Dict[str, str] = {}

    for e in entities:
        rl = _entity_runsize_label(e)
        ru = _entity_runsize_uuid(e)
        if rl and ru:
            # prefer first-seen uuid for a label
            run_map.setdefault(rl, ru)

        cl = _entity_colorspec_label(e)
        cu = _entity_colorspec_uuid(e)
        if cl and cu:
            col_map.setdefault(cl, cu)

        tl = _entity_turnaround_label(e)
        tu = _entity_turnaround_uuid(e)
        if tl and tu:
            ta_map.setdefault(tl, tu)

    runsizes = [{"label": k, "uuid": v} for k, v in sorted(run_map.items(), key=lambda x: _as_int(x[0]) or 10**9)]
    colorspecs = [{"label": k, "uuid": v} for k, v in sorted(col_map.items(), key=lambda x: _norm_colorspec(x[0]))]
    turnarounds = [{"label": k, "uuid": v} for k, v in sorted(ta_map.items(), key=lambda x: x[0])]

    return {"runsizes": runsizes, "colorspecs": colorspecs, "turnaroundtimes": turnarounds}


def _pick_best_entity(
    entities: List[Dict[str, Any]],
    runsize: Optional[str],
    colorspec: Optional[str],
    turnaround: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Find a matching entity in cached baseprices.
    We allow matching by:
      - runsize numeric label "250"
      - colorspec "4/4"
      - turnaround label (optional). If not provided, first match wins.
    """
    notes: List[str] = []
    r_in = _norm(runsize)
    c_in = _norm_colorspec(colorspec)
    t_in = _norm(turnaround)

    # If user gave runsize as int-like, match label int-ish too
    r_int = _as_int(r_in)

    def run_match(e: Dict[str, Any]) -> bool:
        rl = _norm(_entity_runsize_label(e))
        if not rl:
            return False
        if r_int is not None:
            return _as_int(rl) == r_int
        return rl == r_in

    def color_match(e: Dict[str, Any]) -> bool:
        cl = _norm_colorspec(_entity_colorspec_label(e))
        if not cl:
            return False
        return cl == c_in

    def ta_match(e: Dict[str, Any]) -> bool:
        if not t_in:
            return True
        tl = _norm(_entity_turnaround_label(e))
        return tl == t_in

    # Filter progressively (helpful debug notes)
    if r_in:
        entities = [e for e in entities if run_match(e)]
        notes.append(f"runsize_filter={len(entities)}")
    if c_in:
        entities = [e for e in entities if color_match(e)]
        notes.append(f"colorspec_filter={len(entities)}")
    if t_in:
        entities = [e for e in entities if ta_match(e)]
        notes.append(f"turnaround_filter={len(entities)}")

    if not entities:
        return None, notes

    return entities[0], notes


# -----------------------------
# Core health/version endpoints
# -----------------------------
@app.get("/version")
def version():
    return {"service": SERVICE_NAME, "phase": PHASE, "build": BUILD}


@app.get("/ping")
def ping():
    return {"ok": True}


# -----------------------------
# DB endpoints
# -----------------------------
@app.get("/db/ping")
def db_ping():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"ok": True}
    except Exception as e:
        return safe_error({"error": "db ping failed", "message": str(e)}, status_code=500)


@app.post("/db/init")
def db_init():
    """
    Creates tables safely.
    If they already exist, don't crash.
    """
    try:
        Base.metadata.create_all(bind=engine)
        return {"ok": True}
    except Exception as e:
        return safe_error({"error": "db init failed", "message": str(e)}, status_code=500)


# -----------------------------
# 4over endpoints
# -----------------------------
@app.get("/4over/whoami")
def whoami():
    try:
        return fourover.whoami()
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Doorhangers endpoints
# -----------------------------
@app.get("/doorhangers/product/{product_uuid}/baseprices")
def doorhanger_baseprices(product_uuid: str):
    try:
        return fourover.product_baseprices(product_uuid)
    except FourOverError as e:
        return safe_error(
            {
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.post("/doorhangers/import/{product_uuid}")
def doorhanger_import(product_uuid: str):
    """
    Fetch baseprices from 4over and store in DB cache.
    """
    try:
        data = fourover.product_baseprices(product_uuid)
        entities = data.get("entities", [])

        if not isinstance(entities, list) or len(entities) == 0:
            return safe_error(
                {"error": "no baseprices returned", "product_uuid": product_uuid, "raw": data},
                status_code=400,
            )

        with SessionLocal() as db:
            row = BasePriceCache(product_uuid=product_uuid, payload=data)
            db.add(row)
            db.commit()
            db.refresh(row)

            return {"ok": True, "product_uuid": product_uuid, "cache_id": row.id, "entity_count": len(entities)}

    except FourOverError as e:
        return safe_error(
            {
                "error": "4over request failed",
                "status": e.status,
                "url": e.url,
                "body": e.body,
                "canonical": e.canonical,
            },
            status_code=e.status,
        )
    except SQLAlchemyError as e:
        return safe_error({"error": "db error", "message": str(e)}, status_code=500)
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/doorhangers/options")
def doorhangers_options(product_uuid: str = Query(...)):
    """
    Return runsizes/colorspecs/turnaround-times derived from the most recent cached baseprices row.
    """
    try:
        with SessionLocal() as db:
            row = _get_latest_cache(db, product_uuid)
            if not row:
                return safe_error(
                    {"error": "no cache found; run /doorhangers/import/{product_uuid} first", "product_uuid": product_uuid},
                    status_code=404,
                )
            payload = row.payload or {}
            entities = _extract_entities(payload)
            opts = _unique_options(entities)

            return {
                "ok": True,
                "product_uuid": product_uuid,
                "cache_id": row.id,
                "counts": {k: len(v) for k, v in opts.items()},
                "options": opts,
            }
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


@app.get("/doorhangers/quote")
def doorhangers_quote(
    product_uuid: str = Query(...),
    runsize: str = Query(..., description="Human label (e.g., 250)"),
    colorspec: str = Query(..., description="Human label (e.g., 4/4)"),
    turnaround: Optional[str] = Query(None, description="Optional human label"),
    markup_pct: float = Query(0, ge=0, le=300),
):
    """
    Stable quote from cached baseprices (no extra 4over calls).
    This prevents Railway 502 crash loops when invalid UUID combos are passed.
    """
    try:
        with SessionLocal() as db:
            row = _get_latest_cache(db, product_uuid)
            if not row:
                return safe_error(
                    {"error": "no cache found; run /doorhangers/import/{product_uuid} first", "product_uuid": product_uuid},
                    status_code=404,
                )

            payload = row.payload or {}
            entities = _extract_entities(payload)

            match, notes = _pick_best_entity(entities, runsize=runsize, colorspec=colorspec, turnaround=turnaround)
            if not match:
                opts = _unique_options(entities)
                return safe_error(
                    {
                        "error": "no matching combination found in cached baseprices",
                        "product_uuid": product_uuid,
                        "requested": {"runsize": runsize, "colorspec": colorspec, "turnaround": turnaround},
                        "debug_notes": notes,
                        "hint": "Call /doorhangers/options to see valid labels (and UUIDs).",
                        "available_counts": {k: len(v) for k, v in opts.items()},
                    },
                    status_code=404,
                )

            base = _entity_price(match)
            if base is None:
                return safe_error(
                    {
                        "error": "matched combination but could not extract price from entity",
                        "product_uuid": product_uuid,
                        "cache_id": row.id,
                        "matched_entity_keys": sorted(list(match.keys())),
                    },
                    status_code=500,
                )

            sell = round(base * (1.0 + (markup_pct / 100.0)), 2)

            return {
                "ok": True,
                "product_uuid": product_uuid,
                "cache_id": row.id,
                "requested": {"runsize": runsize, "colorspec": colorspec, "turnaround": turnaround, "markup_pct": markup_pct},
                "matched": {
                    "runsize_label": _entity_runsize_label(match),
                    "runsize_uuid": _entity_runsize_uuid(match),
                    "colorspec_label": _entity_colorspec_label(match),
                    "colorspec_uuid": _entity_colorspec_uuid(match),
                    "turnaround_label": _entity_turnaround_label(match),
                    "turnaround_uuid": _entity_turnaround_uuid(match),
                },
                "pricing": {"base_cost": float(base), "sell_price": float(sell)},
            }

    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )


# -----------------------------
# Cache endpoints
# -----------------------------
@app.get("/cache/baseprices")
def cache_baseprices(limit: int = Query(25, ge=1, le=200)):
    """
    Returns the most recent cache rows.
    """
    try:
        with SessionLocal() as db:
            stmt = select(BasePriceCache).order_by(desc(BasePriceCache.id)).limit(limit)
            rows = db.execute(stmt).scalars().all()

            return {
                "ok": True,
                "count": len(rows),
                "rows": [
                    {
                        "id": r.id,
                        "product_uuid": r.product_uuid,
                        "created_at": getattr(r, "created_at", None),
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return safe_error(
            {"error": "unexpected error", "message": str(e), "trace": traceback.format_exc()},
            status_code=500,
        )
