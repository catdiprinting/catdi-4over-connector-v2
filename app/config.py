import os

def env(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip()

def env_int(name: str, default: int) -> int:
    raw = env(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default

# DB (do NOT hard-fail at import time)
DATABASE_URL = env("DATABASE_URL", "").strip()

# 4over (do NOT hard-fail at import time; validate per-request)
FOUR_OVER_BASE_URL = env("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_API_PREFIX = env("FOUR_OVER_API_PREFIX", "").strip()  # e.g. "printproducts"
FOUR_OVER_APIKEY = env("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = env("FOUR_OVER_PRIVATE_KEY", "")
FOUR_OVER_TIMEOUT = env_int("FOUR_OVER_TIMEOUT", 30)

# Normalize prefix to "" or "/something" without trailing slash
if FOUR_OVER_API_PREFIX:
    if not FOUR_OVER_API_PREFIX.startswith("/"):
        FOUR_OVER_API_PREFIX = "/" + FOUR_OVER_API_PREFIX
    FOUR_OVER_API_PREFIX = FOUR_OVER_API_PREFIX.rstrip("/")
