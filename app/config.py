import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "catdi-4over-connector")

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "").strip("/")  # usually ""
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "").strip()
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "").strip()

FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

# Railway sometimes uses postgres:// which SQLAlchemy 2 expects as postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
