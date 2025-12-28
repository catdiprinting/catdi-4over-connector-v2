```python
# main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from db import init_db, get_db
from routes_catalog import router as catalog_router
from catalog_sync import upsert_catalog

import fourover_client  # must exist in this same repo root


app = FastAPI(title="catdi-4over-connector-v2")


@app.on_event("startup")
def startup():
    # Creates tables if they don't exist (Postgres on Railway or local sqlite)
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


# Catalog endpoints for Woo/UX dropdowns:
#  - GET /catalog/sizes
#  - GET /catalog/lines?size_id=...
#  - GET /catalog/resolve?size_id=...&line_id=...
app.include_router(catalog_router)


@app.post("/admin/sync-catalog")
def sync_catalog(db: Session = Depends(get_db)):
    """
    Pull product list from 4over and cache it in DB for fast UX dropdowns.

    IMPORTANT:
    - This assumes fourover_client.list_products() returns a list[dict]
      with keys: product_uuid, product_code, product_description (optional)
    - If your fourover_client uses a different function name or key names,
      update here (and/or in catalog_sync.py).
    """
    if not hasattr(fourover_client, "list_products"):
        raise HTTPException(
            status_code=500,
            detail="fourover_client.list_products() not found. Paste fourover_client.py so I can wire it correctly.",
        )

    entities = fourover_client.list_products()

    if not isinstance(entities, list):
        raise HTTPException(
            status_code=500,
            detail="list_products() must return a list of product dicts.",
        )

    result = upsert_catalog(db, entities)
    return {"ok": True, "synced": result, "count": len(entities)}
```
