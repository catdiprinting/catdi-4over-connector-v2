import os

def _strip_trailing_slash(s: str) -> str:
    return s[:-1] if s.endswith("/") else s

FOUR_OVER_BASE_URL = _strip_trailing_slash(os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com"))
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "printproducts").strip("/")

FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")

FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
