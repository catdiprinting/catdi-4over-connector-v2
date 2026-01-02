import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")

FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

# markup for later (not applied yet in DB rows; keep here for pricing calc phase)
DEFAULT_MARKUP_PCT = float(os.getenv("DEFAULT_MARKUP_PCT", "0.20"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
