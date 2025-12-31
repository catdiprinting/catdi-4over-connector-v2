import os

# ─────────────────────────────────────────────
# Service Metadata
# ─────────────────────────────────────────────
SERVICE_NAME = os.getenv("SERVICE_NAME", "catdi-4over-connector")
PHASE = os.getenv("PHASE", "0.9")
BUILD = os.getenv("BUILD", "ROOT_MAIN_PY_V2")

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# ─────────────────────────────────────────────
# 4OVER API CONFIG
# ─────────────────────────────────────────────
FOUR_OVER_BASE_URL = os.getenv(
    "FOUR_OVER_BASE_URL",
    "https://api.4over.com"
).rstrip("/")

FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
