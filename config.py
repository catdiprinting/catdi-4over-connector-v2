# config.py
import os

def env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    if v is not None:
        v = v.strip()
    return v

FOUR_OVER_APIKEY = env("FOUR_OVER_APIKEY")         # e.g. "catdi"
FOUR_OVER_PRIVATE_KEY = env("FOUR_OVER_PRIVATE_KEY")
FOUR_OVER_BASE_URL = env("FOUR_OVER_BASE_URL", "https://api.4over.com")

DATABASE_URL = env("DATABASE_URL", "sqlite:///./local.db")

DEBUG = (env("DEBUG", "0") == "1")
