from fastapi import APIRouter, HTTPException
from fourover_client import client

router = APIRouter(prefix="/doorhangers", tags=["doorhangers"])

@router.get("/product/{product_uuid}/optiongroups")
def get_optiongroups(product_uuid: str):
    try:
        return client.get(
            f"/printproducts/products/{product_uuid}/optiongroups"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/product/{product_uuid}/baseprices")
def get_baseprices(product_uuid: str):
    try:
        return client.get(
            f"/printproducts/products/{product_uuid}/baseprices"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import/{product_uuid}")
def import_product(product_uuid: str):
    """
    TEMP: fetch-only import
    DB persistence comes next step
    """
    try:
        baseprices = client.get(
            f"/printproducts/products/{product_uuid}/baseprices"
        )
        return {
            "ok": True,
            "product_uuid": product_uuid,
            "baseprice_count": len(baseprices.get("entities", [])),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
