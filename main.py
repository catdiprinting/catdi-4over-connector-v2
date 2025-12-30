from fastapi import FastAPI
from db import engine, Base

from pricing_tester import router as pricing_router

from pricing_tester import router as pricing_router
app.include_router(pricing_router)


app = FastAPI(title="catdi-4over-connector")

# Create pricing tables
Base.metadata.create_all(bind=engine)

# Mount pricing tester
app.include_router(pricing_router)


@app.get("/")
def root():
    return {"ok": True, "service": "catdi-4over-connector"}
