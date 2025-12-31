# config.py
import os
from pydantic import BaseModel


class Settings(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./local.db")

    FOUR_OVER_BASE_URL: str = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
    FOUR_OVER_APIKEY: str = os.getenv("FOUR_OVER_APIKEY", "")
    FOUR_OVER_PRIVATE_KEY: str = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "catdi-4over-connector")
    PHASE: str = os.getenv("PHASE", "0.6")
    BUILD: str = os.getenv("BUILD", "root-layout-db-ping-fourover-v1")


settings = Settings()
