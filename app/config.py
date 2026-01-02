# app/config.py
import os


def env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


FOUR_OVER_BASE_URL = env("FOUR_OVER_BASE_URL", "https://api.4over.com")
FOUR_OVER_APIKEY = env("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = env("FOUR_OVER_PRIVATE_KEY")

DATABASE_URL = env("DATABASE_URL", "sqlite:///./local.db")
