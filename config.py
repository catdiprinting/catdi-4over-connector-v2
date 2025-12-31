import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")

missing = []
if not FOUR_OVER_APIKEY:
    missing.append("FOUR_OVER_APIKEY")
if not FOUR_OVER_PRIVATE_KEY:
    missing.append("FOUR_OVER_PRIVATE_KEY")
if missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
