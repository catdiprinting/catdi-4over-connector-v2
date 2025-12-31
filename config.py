# config.py
import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "").strip()
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "").strip()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db").strip()

# Normalize Railway/Heroku style
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
