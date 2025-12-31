import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import Base, engine
from routes_catalog import router as catalog_router
from doorhangers import router as doorhangers_router

APP_PHASE = os.getenv("APP_PHASE", "0.9")
APP_BUILD = os.getenv("APP_BUILD", "ROOT_MAIN_PY_V2")
SERVICE_NAME = os.getenv("SERVICE_NAME", "catdi-4over-connector")


def create_app() -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, version=APP_PHASE)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup():
        # Create tables if they don't exist (safe to run every boot)
        Base.metadata.create_all(bind=engine)

    @app.get("/")
    def root():
        return {"service": SERVICE_NAME, "phase": APP_PHASE, "build": APP_BUILD}

    @app.get("/version")
    def version():
        return {"service": SERVICE_NAME, "phase": APP_PHASE, "build": APP_BUILD}

    @app.get("/health")
    def health():
        return {"ok": True, "service": SERVICE_NAME, "phase": APP_PHASE, "build": APP_BUILD}

    app.include_router(catalog_router)
    app.include_router(doorhangers_router)
    return app


app = create_app()
