import os

# 4over
FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com").rstrip("/")
# Prefix for catalog endpoints (NOT for /whoami)
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

# DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
