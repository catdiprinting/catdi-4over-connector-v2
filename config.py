import os

def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

# 4over
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").strip().rstrip("/")
FOUR_OVER_APIKEY = _req("FOUR_OVER_APIKEY")          # public key (your apikey / username)
FOUR_OVER_PRIVATE_KEY = _req("FOUR_OVER_PRIVATE_KEY")# private key

# DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db").strip()

# Safety / debugging
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes", "y", "on")
SERVICE_NAME = os.getenv("SERVICE_NAME", "catdi-4over-connector")
PHASE = os.getenv("PHASE", "0.9")
BUILD = os.getenv("BUILD", "ROOT_MAIN_PY_V4_SAFE_ERRORS")
