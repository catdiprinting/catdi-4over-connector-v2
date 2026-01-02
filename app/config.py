import os

def env(name: str, default: str | None = None):
    v = os.getenv(name, default)
    return v.strip() if v else None

FOUR_OVER_BASE_URL = env("FOUR_OVER_BASE_URL", "https://api.4over.com")
FOUR_OVER_API_PREFIX = env("FOUR_OVER_API_PREFIX", "printproducts")
FOUR_OVER_TIMEOUT = env("FOUR_OVER_TIMEOUT", "30")

FOUR_OVER_APIKEY = env("FOUR_OVER_APIKEY")
FOUR_OVER_PRIVATE_KEY = env("FOUR_OVER_PRIVATE_KEY")
