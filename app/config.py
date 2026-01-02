import os

FOUR_OVER_BASE_URL = os.getenv("FOUR_OVER_BASE_URL", "https://api.4over.com")
FOUR_OVER_API_PREFIX = os.getenv("FOUR_OVER_API_PREFIX", "printproducts")
FOUR_OVER_TIMEOUT = int(os.getenv("FOUR_OVER_TIMEOUT", "30"))
FOUR_OVER_APIKEY = os.getenv("FOUR_OVER_APIKEY", "")
FOUR_OVER_PRIVATE_KEY = os.getenv("FOUR_OVER_PRIVATE_KEY", "")
