import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from fourover_client import FourOverError, client
from db import ensure_schema, upsert_baseprice_cache, latest_baseprice_cache

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])


def _safe_decimal(s: Any) -> Decimal:
    try:
        return Decimal(str(s))
    except Exception:
        return Decimal("0")


def _money(d: Decimal) -> str:
    # 4 decimals to preserve accuracy; you can display 2 in UI later
    return str(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _extract_option_values(optiongroups_payload: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """
    Converts 4over optiongroups into a normalized dict:
    {
      "size": [{"uuid": "...", "label": "3.5 x 8.5"}, ...],
      "stock": [...],
      "coating": [...],
      "turnaround": [...],
      "runsize": [...],
      "colorspec": [...]
    }

    Works even if the API's group names vary a bit.
    """
    out: Dict[str, List[Dict[str, str]]] = {}
    entities = optiongroups_payload.get("entities") or []

    def bucket(name: str) -> str:
        n = (name or "").strip().lower()
        if "run" in n and "size" in n:
            return "runsize"
        if "color" in n or "colors" in n:
            return "colorspec"
        if "size" in n:
            return "size"
        if "stock" in n or "paper" in n:
            return "stock"
        if "coat" in n or "lam" in n or "uv" in n or "aq" in n:
            return "coating"
        if "turn" in n or "production" in n or "days" in n:
            return "turnaround"
        return (name or "other").strip().lower() or "other"

    for grp in entities:
        grp_name = grp.get("name") or grp.get("option_group_name") or ""
        key = bucket(grp_name)

        values = grp.get("values") or grp.get("entities") or []
        norm_vals = []
        for v in values:
            uuid = v.get("product_option_uuid") or v.get("option_uuid") or v.get("uuid")
            label = v.get("value") or v.get("name") or v.get("label")
            if uuid and label:
                norm_vals.append({"uuid": str(uuid), "label": str(label)})

        if norm_vals:
            out.setdefault(key, [])
            # dedupe by uuid
            seen = set(x["uuid"] for x in out[key])
            for nv in norm_vals:
                if nv["uuid"] not in seen:
                    out[key].append(nv)
                    seen.add(nv["uuid"])

    return out


def _find_price_row(baseprices_payload: Dict[str, Any], *, runsize: Optional[str], colorspec: Optional[str],
                    runsize_uuid: Optional[str], colorspec_uuid: Optional[str]) -> Optional[Dict[str, Any]]:
    rows = baseprices_payload.get("entities") or []

    # Prefer UUID match when provided
    if runsize_uuid and colorspec_uuid:
        for r in rows:
            if str(r.get("runsize_uuid")) == runsize_uuid and str(r.get("colorspec_uuid")) == colorspec_uuid:
                return r

    # Fallback to label match
    if runsize and colorspec:
        rs = str(runsize).strip()
        cs = str(colorspec).strip()
        for r in rows:
            if str(r.get("runsize")) == rs and str(r.get("colorspec")) == cs:
                return r

    return None


@router.post("/import/{product_uuid}")
def import_baseprices(product_uuid: str):
    """
    Fetch baseprices from 4over and UPSERT into DB (one row per product_uuid).
    """
    try:
        ensure_schema()
        payload = client.get(f"/printproducts/products/{product_uuid}/baseprices")
        cache_id = upsert_baseprice_cache(product_uuid, json.dumps(payload))
        return {"ok": True, "product_uuid": product_uuid, "cache_id": cache_id}
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": getattr(e, "canonical", None),
                }
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "import_failed", "message": str(e)})


@router.get("/options")
def doorhanger_options(product_uuid: str = Query(...)):
    """
    Pull optiongroups live from 4over (not cached yet).
    Returns normalized option buckets + convenience runsizes/colorspecs.
    """
    try:
        payload = client.get(f"/printproducts/products/{product_uuid}/optiongroups")
        buckets = _extract_option_values(payload)

        # convenience lists (your UI already expects these)
        runsizes = [{"runsize_uuid": x["uuid"], "runsize": x["label"]} for x in buckets.get("runsize", [])]
        colorspecs = [{"colorspec_uuid": x["uuid"], "colorspec": x["label"]} for x in buckets.get("colorspec", [])]

        return {
            "ok": True,
            "product_uuid": product_uuid,
            "runsizes": runsizes,
            "colorspecs": colorspecs,
            "option_buckets": buckets,  # includes size/stock/coating/turnaround when present
            "source": {"used_cache": False},
        }
    except FourOverError as e:
        return JSONResponse(
            status_code=401 if e.status == 401 else 502,
            content={
                "detail": {
                    "error": "4over_http_error",
                    "status_code": e.status,
                    "url": e.url,
                    "body": e.body,
                    "canonical": getattr(e, "canonical", None),
                }
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "options_failed", "message": str(e)})


@router.get("/quote")
def doorhanger_quote(
    product_uuid: str = Query(...),
    markup_pct: float = Query(25.0, ge=0.0, le=500.0),

    # Match by labels:
    runsize: Optional[str] = Query(None),
    colorspec: Optional[str] = Query(None),

    # Or match by UUIDs:
    runsize_uuid: Optional[str] = Query(None),
    colorspec_uuid: Optional[str] = Query(None),
):
    """
    Quote using cached baseprices (DB). If missing cache: return 404 with guidance.
    """
    ensure_schema()
    row = latest_baseprice_cache(product_uuid)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_cache",
                "message": "No baseprice cache found. Run POST /doorhangers/import/{product_uuid} first.",
                "product_uuid": product_uuid,
            },
        )

    try:
        payload = json.loads(row["payload_json"])
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "bad_cache_json", "message": str(e)})

    match = _find_price_row(
        payload,
        runsize=runsize,
        colorspec=colorspec,
        runsize_uuid=runsize_uuid,
        colorspec_uuid=colorspec_uuid,
    )
    if not match:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_match",
                "message": "No matching baseprice row found for provided runsize/colorspec.",
                "product_uuid": product_uuid,
                "provided": {
                    "runsize": runsize,
                    "colorspec": colorspec,
                    "runsize_uuid": runsize_uuid,
                    "colorspec_uuid": colorspec_uuid,
                },
            },
        )

    base = _safe_decimal(match.get("product_baseprice"))
    pct = Decimal(str(markup_pct))
    sell = base * (Decimal("1") + (pct / Decimal("100")))
    qty = int(str(match.get("runsize") or "0").strip() or "0") if (match.get("runsize") is not None) else 0
    unit = (sell / Decimal(qty)) if qty else Decimal("0")

    return {
        "ok": True,
        "product_uuid": product_uuid,
        "match": {
            "runsize_uuid": match.get("runsize_uuid"),
            "runsize": match.get("runsize"),
            "colorspec_uuid": match.get("colorspec_uuid"),
            "colorspec": match.get("colorspec"),
        },
        "pricing": {
            "base_price": str(match.get("product_baseprice")),
            "markup_pct": float(markup_pct),
            "sell_price": _money(sell),
            "unit_price": _money(unit),
            "qty": qty,
        },
        "source": {"used_cache": True, "cache_id": row["id"], "auto_fetch": False},
    }
