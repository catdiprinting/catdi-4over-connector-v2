import os

def _get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    if v is None:
        return None
    # strip ONLY leading/trailing whitespace; do NOT modify internal chars
    return v.strip()

FOUR_OVER_BASE_URL = _get("FOUR_OVER_BASE_URL", "https://api.4over.com")
FOUR_OVER_API_PREFIX = _get("FOUR_OVER_API_PREFIX", "printproducts")
FOUR_OVER_TIMEOUT = _get("FOUR_OVER_TIMEOUT", "30")

FOUR_OVER_APIKEY = _get("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = _get("FOUR_OVER_PRIVATE_KEY")
