from fastapi import APIRouter
from fourover_client import FourOverClient

router = APIRouter(prefix="/doorhangers")

client = FourOverClient()

@router.get("/product/{product_uuid}/optiongroups")
def optiongroups(product_uuid: str):
    return client.product_optiongroups(product_uuid)

@router.get("/product/{product_uuid}/baseprices")
def baseprices(product_uuid: str):
    return client.product_baseprices(product_uuid)
