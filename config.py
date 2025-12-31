import os

def getenv_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val

# Railway / Postgres
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# 4over
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")

# Debug toggles
DEBUG = os.getenv("DEBUG", "0") == "1"
